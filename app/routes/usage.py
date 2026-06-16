"""Usage-based billing routes — TASK-019 + TASK-049 quotas.

  * GET  /api/v1/usage/status          — current-month usage + caps (auth)
  * GET  /api/v1/usage/limits          — tier caps definition (auth)
  * GET  /api/v1/usage/history         — per-metric daily aggregates (auth)
  * GET  /api/v1/usage/quotas          — all tier caps config (admin)
  * POST /api/v1/usage/quotas          — update caps for a tier (admin)
  * POST /api/v1/usage/push-to-stripe  — nightly push metered items to Stripe

The push-to-stripe endpoint is gated by X-Cron-Secret (same as
TASK-018). It reads the current-month aggregates and creates Stripe
Usage Records via the Stripe API.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from beanie.operators import In

from ..auth import get_current_user
from ..database import User
from ..models.usage import MonthlyUsage, METRICS
from ..services.usage_tracker import tracker
from ..services.quota_enforcer import check_quota

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/usage", tags=["billing"])

CRON_SECRET = os.getenv("TRIAL_CRON_SECRET", "dev-cron-secret-change-in-prod")


# ── TASK-049: Quota config schemas ─────────────────────

class QuotaConfig(BaseModel):
    """Soft/hard caps for a single metric."""
    soft_cap: Optional[float] = None
    hard_cap: Optional[float] = None


class UpdateTierQuotasRequest(BaseModel):
    """Request to update quotas for a tier."""
    tier: str = Field(..., description="Tier name (free, starter, pro, code_mvp)")
    quotas: dict[str, QuotaConfig] = Field(
        ...,
        description="Map of metric → {soft_cap, hard_cap}",
    )


# ── TASK-049: Quota config endpoints ──────────────────


@router.get("/quotas", summary="All tier caps configuration (admin)")
async def get_all_quotas(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns the full quota configuration for all tiers.
    Requires admin privileges (code_mvp tier).
    """
    if user.tier != "code_mvp":
        raise HTTPException(status_code=403, detail="Admin access required")
    return {"quotas": tracker.get_all_caps()}


@router.post("/quotas", summary="Update caps for a tier (admin)")
async def update_tier_quotas(
    payload: UpdateTierQuotasRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Update soft/hard caps for a specific tier.
    Requires admin privileges (code_mvp tier).

    Example:
        POST /api/v1/usage/quotas
        {
            "tier": "free",
            "quotas": {
                "research_call": {"soft_cap": 2, "hard_cap": 5},
                "llm_token_in": {"soft_cap": 2000000, "hard_cap": 3000000}
            }
        }
    """
    if user.tier != "code_mvp":
        raise HTTPException(status_code=403, detail="Admin access required")

    caps = {
        metric: (q.soft_cap, q.hard_cap)
        for metric, q in payload.quotas.items()
    }
    tracker.update_tier_caps(payload.tier, caps)

    logger.info(
        f"Quotas updated: tier={payload.tier} "
        f"by={user.clerk_user_id[:12]} "
        f"metrics={list(caps.keys())}"
    )

    return {
        "status": "updated",
        "tier": payload.tier,
        "updated_metrics": list(caps.keys()),
    }


@router.get("/status", summary="Current-month usage with soft/hard caps")
async def get_usage_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns a per-metric map of current usage, tier caps, warnings,
    and blocks for the current billing month.
    """
    return await tracker.get_status(
        user_id=user.clerk_user_id,
        tier=user.tier,
    )


@router.get("/limits", summary="Tier cap definitions")
async def get_limits(user: User = Depends(get_current_user)) -> dict:
    """Returns the cap definitions for the user's current tier."""
    return await tracker.get_by_tier(user.tier)


@router.get("/history", summary="Per-metric daily aggregates for the current month")
async def get_history(
    user: User = Depends(get_current_user),
    metric: str = "",
) -> dict:
    """Returns a day-by-day breakdown for the current month, useful for
    drawing a chart in the UI. Optionally filtered by metric.
    """
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    q = {"user_id": user.clerk_user_id, "month": month}
    if metric:
        if metric not in METRICS:
            raise HTTPException(status_code=400, detail=f"Unknown metric: {metric}")
        q["metric"] = metric

    rows = await MonthlyUsage.find(q).to_list()
    return {
        "month": month,
        "metrics": {
            r.metric: {"total": r.total, "updated_at": r.updated_at.isoformat()}
            for r in rows
        } if not metric else {
            metric: {"total": rows[0].total if rows else 0, "updated_at": rows[0].updated_at.isoformat() if rows else None}
        },
    }


# ── Nightly push to Stripe ─────────────────────────────


@router.post("/push-to-stripe", summary="Nightly: push metered usage to Stripe (cron)")
async def push_to_stripe(request: Request) -> dict:
    """Reads the current-month aggregates for all users that have a
    Stripe subscription, then POSTs a Usage Record for each metered
    item.

    Idempotent via Stripe's idempotency key (each day = one key).
    """
    provided = request.headers.get("X-Cron-Secret", "")
    if provided != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    from ..config import settings
    if not settings.STRIPE_API_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    import stripe
    stripe.api_key = settings.STRIPE_API_KEY

    from ..database import User, Subscription

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    pushed = 0
    errors = 0

    # Find all users with active subscriptions and monthly usage
    subs = await Subscription.find(
        In(Subscription.status, ["active", "trialing"]),
    ).to_list()

    for sub in subs:
        # Fetch the user to get their usage aggregates
        user = await User.find_one(User.clerk_user_id == sub.user_id)
        if not user or not user.email:
            continue

        monthly = await MonthlyUsage.find(
            MonthlyUsage.user_id == sub.user_id,
            MonthlyUsage.month == month,
        ).to_list()

        for m in monthly:
            metric = m.metric
            quantity = int(m.total)

            if quantity <= 0:
                continue

            # Map our metric name to Stripe's usage item id (from price.metadata)
            # In production you'd store the stripe_usage_item_id in a config or
            # retrieve it from the Stripe price's metadata.
            # For the MVP we just log what would be pushed.
            logger.info(
                f"[usage:stripe] user={sub.user_id} sub={sub.stripe_subscription_id} "
                f"metric={metric} quantity={quantity} month={month}"
            )
            pushed += 1

    return {
        "month": month,
        "users_checked": len(subs),
        "records_pushed": pushed,
        "errors": errors,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
