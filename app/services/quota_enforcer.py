"""Quota Enforcer — TASK-049.

Middleware-style service that checks usage quotas before operations:

  - Soft cap (80%+): returns warning, allows operation
  - Hard cap (100%): blocks with 429 + upgrade CTA

Usage (in route handlers):
    from app.services.quota_enforcer import check_quota

    # Before consuming a metered resource:
    result = await check_quota(user, "research_call", increment=1)
    if result["blocked"]:
        raise HTTPException(429, detail=result["error"])

    # Or use the dependency:
    @router.post("/research")
    async def start_research(user=Depends(get_current_user)):
        check = await require_quota(user, "research_call")
        # ... proceed

Integration with UsageTracker:
    The enforcer calls tracker.get_status() to check current usage,
    then calculates if the increment would exceed caps.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

from ..config import settings
from ..database import User
from ..models.usage import METRICS
from .usage_tracker import tracker
from .usage_alerts import check_and_alert

logger = logging.getLogger(__name__)


# ── HTTP Exception Factory ─────────────────────────────

def _quota_exceeded_response(
    metric: str,
    current: float,
    hard_cap: float,
    tier: str,
) -> HTTPException:
    """Build a 429 response with upgrade CTA when hard cap hit."""
    metric_label = metric.replace("_", " ").title()
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": f"{metric_label} limit reached",
            "metric": metric,
            "current": current,
            "limit": hard_cap,
            "tier": tier,
            "message": (
                f"You've used {current:.0f} / {hard_cap:.0f} {metric_label}. "
                f"Upgrade your plan to increase your limit."
            ),
            "upgrade_url": "/settings",
            "code": "quota_exceeded",
        },
    )


# ── Main Check Function ────────────────────────────────

async def check_quota(
    user: User,
    metric: str,
    increment: float = 1.0,
    *,
    send_alerts: bool = True,
) -> dict:
    """Check if the user can perform an operation on a metered resource.

    Args:
        user: The user performing the operation.
        metric: The metered metric name (e.g. "research_call").
        increment: How much this operation would consume (default 1).
        send_alerts: Whether to send threshold email alerts.

    Returns:
        {
            "allowed": bool,
            "blocked": bool,     # True if hard cap hit
            "warning": str | None,  # "soft" if at soft cap
            "error": str | None,    # Error detail if blocked
            "current": float,
            "soft_cap": float | None,
            "hard_cap": float | None,
            "pct": float,
            "alerted": str,      # "none" | "soft" | "hard"
        }

    Raises:
        HTTPException(429) if blocked (for direct dependency use).
    """
    if metric not in METRICS:
        return {
            "allowed": True,
            "blocked": False,
            "warning": None,
            "error": None,
            "current": 0,
            "soft_cap": None,
            "hard_cap": None,
            "pct": 0,
            "alerted": "none",
        }

    # Get current usage
    status_data = await tracker.get_status(
        user_id=user.clerk_user_id,
        tier=user.tier,
    )

    metric_status = status_data.get(metric, {})
    current = metric_status.get("current", 0.0)
    soft_cap = metric_status.get("soft_cap")
    hard_cap = metric_status.get("hard_cap")
    pct = metric_status.get("pct", 0.0)

    # Projected usage after this operation
    projected = current + increment

    result = {
        "allowed": True,
        "blocked": False,
        "warning": None,
        "error": None,
        "current": current,
        "soft_cap": soft_cap,
        "hard_cap": hard_cap,
        "pct": pct,
        "alerted": "none",
    }

    # Check hard cap (projected)
    if hard_cap is not None and projected > hard_cap:
        result["allowed"] = False
        result["blocked"] = True
        result["error"] = (
            f"You've used {current:.0f} / {hard_cap:.0f} "
            f"{metric.replace('_', ' ').title()}. "
            f"Upgrade your plan to increase your limit."
        )
        result["warning"] = "hard"

        # Send alert
        if send_alerts:
            alert = await check_and_alert(
                user=user,
                metric=metric,
                current=current,
                soft_cap=soft_cap,
                hard_cap=hard_cap,
            )
            result["alerted"] = alert["alerted"]

        return result

    # Check soft cap
    if soft_cap is not None and projected >= soft_cap * 0.8:
        result["warning"] = "soft" if projected < hard_cap else "hard"

        # Send alert only on actual crossing (not just approaching)
        if send_alerts and current <= soft_cap < projected:
            alert = await check_and_alert(
                user=user,
                metric=metric,
                current=projected,
                soft_cap=soft_cap,
                hard_cap=hard_cap,
            )
            result["alerted"] = alert["alerted"]

    return result


async def require_quota(
    user: User,
    metric: str,
    increment: float = 1.0,
    *,
    send_alerts: bool = True,
) -> dict:
    """Like check_quota but raises HTTPException(429) if blocked.

    Use as a dependency in route handlers:

        @router.post("/research")
        async def start_research(user=Depends(get_current_user)):
            await require_quota(user, "research_call")
            # ... proceed
    """
    result = await check_quota(
        user=user,
        metric=metric,
        increment=increment,
        send_alerts=send_alerts,
    )

    if result["blocked"]:
        raise _quota_exceeded_response(
            metric=metric,
            current=result["current"],
            hard_cap=result["hard_cap"] or 0,
            tier=user.tier,
        )

    return result
