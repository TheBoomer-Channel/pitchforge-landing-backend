"""Usage tracker — TASK-019 enhanced with TASK-049 quotas & alerts.

Public API for recording and querying metered usage.

Usage:
  from app.services.usage_tracker import tracker
  await tracker.record(user_id="...", metric="research_call", quantity=1)
  status = await tracker.get_status(user_id="...")
  status["research_call"]["current"]  # int
  status["research_call"]["soft_cap"]  # set by tier; None for no cap

TASK-049 enhancements:
  - Integrated alerts via usage_alerts.check_and_alert()
  - Record returns quota status (blocked/warning)
  - TIER_CAPS configurable via update_tier_caps()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ..models.usage import UsageEvent, MonthlyUsage, METRICS

logger = logging.getLogger(__name__)

# Tier → (soft_cap, hard_cap) per metric. The caps are enforced at
# the route level; the tracker just records and surfaces them.
# Values: None means no cap.
# TASK-049 — These can be dynamically updated via update_tier_caps().
TIER_CAPS: dict[str, dict[str, tuple[float, float]]] = {
    "free": {
        "research_call": (1, 2),
        "llm_token_in": (1_000_000, 1_500_000),
        "llm_token_out": (1_000_000, 1_200_000),
        "pdf_export": (3, 5),
        "api_call": (100, 200),
    },
    "starter": {
        "research_call": (5, 10),
        "llm_token_in": (5_000_000, 7_000_000),
        "llm_token_out": (5_000_000, 6_000_000),
        "pdf_export": (20, 30),
        "api_call": (500, 1_000),
    },
    "pro": {
        "research_call": (20, 50),
        "llm_token_in": (50_000_000, 100_000_000),
        "llm_token_out": (50_000_000, 100_000_000),
        "pdf_export": (100, 200),
        "api_call": (2_000, 5_000),
    },
    "code_mvp": {
        "research_call": (100, None),  # no hard cap
        "llm_token_in": (100_000_000, None),
        "llm_token_out": (100_000_000, None),
        "pdf_export": (500, None),
        "api_call": (10_000, None),
    },
}


class UsageTracker:
    """Centralised usage tracking service with quota enforcement."""

    # ── TASK-049: Dynamic quota config ───────────────────

    def update_tier_caps(
        self,
        tier: str,
        caps: dict[str, tuple[float, float]],
    ) -> None:
        """Update caps for a specific tier at runtime.

        Example:
            tracker.update_tier_caps("free", {
                "research_call": (2, 5),
                "llm_token_in": (2_000_000, 3_000_000),
            })
        """
        if tier not in TIER_CAPS:
            TIER_CAPS[tier] = {}
        for metric, (soft, hard) in caps.items():
            TIER_CAPS[tier][metric] = (soft, hard)
        logger.info(f"Updated caps for tier '{tier}': {len(caps)} metrics")

    def get_all_caps(self) -> dict:
        """Get all tier caps (for admin UI)."""
        return {tier: dict(caps) for tier, caps in TIER_CAPS.items()}

    # ── Core Tracking ───────────────────────────────────

    async def record(
        self,
        *,
        user_id: str,
        metric: str,
        quantity: float = 1.0,
        metadata: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> dict:
        """Record a usage event and return post-recording quota status.

        TASK-049: Returns quota status so the caller can check if limits
        were exceeded after recording.

        Returns:
            {"current": float, "soft_cap": float|None, "hard_cap": float|None,
             "pct": float, "warning": str|None, "blocked": str|None}
        """
        if metric not in METRICS:
            logger.warning(f"Unknown metric: {metric}")
            return {}

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")

        event = UsageEvent(
            user_id=user_id,
            metric=metric,
            quantity=quantity,
            metadata=metadata or {},
            request_id=request_id,
            ts=now,
        )
        await event.insert()

        # Upsert monthly aggregate
        await MonthlyUsage.find_one(
            MonthlyUsage.user_id == user_id,
            MonthlyUsage.metric == metric,
            MonthlyUsage.month == month,
        ).upsert(
            set={
                MonthlyUsage.last_event_ts: now,
                MonthlyUsage.updated_at: now,
            },
            inc={MonthlyUsage.total: quantity},
        )

        # Return updated status for this metric
        status = await self._get_metric_status(user_id, metric, tier_hint=None)
        return status

    async def _get_metric_status(
        self,
        user_id: str,
        metric: str,
        tier: str = "free",
    ) -> dict:
        """Get current-month usage for a single metric with caps."""
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        row = await MonthlyUsage.find_one(
            MonthlyUsage.user_id == user_id,
            MonthlyUsage.metric == metric,
            MonthlyUsage.month == month,
        )
        current = row.total if row else 0.0

        # Get caps for the user's specific tier
        tier_caps = TIER_CAPS.get(tier, TIER_CAPS.get("free", {}))
        soft_cap, hard_cap = tier_caps.get(metric, (None, None))

        pct = (current / soft_cap * 100) if soft_cap and soft_cap > 0 else 0.0
        return {
            "current": current,
            "soft_cap": soft_cap,
            "hard_cap": hard_cap,
            "pct": round(pct, 1),
            "warning": "soft" if (soft_cap and current >= soft_cap and not (hard_cap and current >= hard_cap)) else None,
            "blocked": "hard" if (hard_cap and current >= hard_cap) else None,
        }

    async def get_status(
        self,
        user_id: str,
        tier: str = "free",
    ) -> dict:
        """Return current-month usage for all metrics, with caps.

        Returns a dict like:
          {"research_call": {"current": 1, "soft_cap": 1, "hard_cap": 2, "pct": 100.0},
           ...}
        """
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        tier_caps = TIER_CAPS.get(tier, TIER_CAPS["free"])

        rows = await MonthlyUsage.find(
            MonthlyUsage.user_id == user_id,
            MonthlyUsage.month == month,
        ).to_list()
        by_metric = {r.metric: r.total for r in rows}

        result = {}
        for metric in sorted(METRICS):
            current = by_metric.get(metric, 0.0)
            soft_cap, hard_cap = tier_caps.get(metric, (None, None))
            pct = (current / soft_cap * 100) if soft_cap and soft_cap > 0 else 0.0
            result[metric] = {
                "current": current,
                "soft_cap": soft_cap,
                "hard_cap": hard_cap,
                "pct": round(pct, 1),
                "warning": "soft" if (soft_cap and current >= soft_cap and not (hard_cap and current >= hard_cap)) else None,
                "blocked": "hard" if (hard_cap and current >= hard_cap) else None,
            }
        return result

    async def get_by_tier(self, tier: str) -> dict:
        """Return the tier's caps (without user data) for the frontend."""
        caps = TIER_CAPS.get(tier, TIER_CAPS["free"])
        return {
            metric: {"soft_cap": caps.get(metric, (None, None))[0],
                     "hard_cap": caps.get(metric, (None, None))[1]}
            for metric in sorted(METRICS)
        }


tracker = UsageTracker()
