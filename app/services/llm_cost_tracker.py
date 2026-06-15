"""LLM Cost Tracker — TASK-026.

Records every LLM API call cost and provides:
  - Per-provider, per-model cost tracking
  - Daily aggregation for budget monitoring
  - Slack alerts when budget thresholds are exceeded
  - Summary data for dashboard visualization

Usage:
    from app.services.llm_cost_tracker import cost_tracker

    # Record a cost (called automatically by the LLM client)
    await cost_tracker.record(
        provider="deepseek",
        model="deepseek-chat",
        prompt_tokens=500,
        completion_tokens=200,
        cost_usd=0.0004,
        user_id="user_abc",
        metadata={"task": "research_synthesis"},
    )

    # Get daily summary
    summary = await cost_tracker.get_daily_summary()

    # Check budget and alert if exceeded
    await cost_tracker.check_budget_alert()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ..config import settings
from ..models.llm_cost import LLMCost

logger = logging.getLogger(__name__)

# ── DeepSeek pricing (USD per 1K tokens) ───────────────
# Prices as of 2026-06. Update when DeepSeek changes pricing.
# Source: https://api-docs.deepseek.com/quick_start/pricing
PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {       # Flash v4 — fast, cheap
        "input_per_1k": 0.00027,
        "output_per_1k": 0.00110,
        "cached_input_per_1k": 0.00007,  # 75% discount on cached tokens
    },
    "deepseek-reasoner": {  # Pro v4 — complex reasoning
        "input_per_1k": 0.00219,
        "output_per_1k": 0.00894,
    },
    # Fallback pricing for unknown models
    "_default": {
        "input_per_1k": 0.00100,
        "output_per_1k": 0.00200,
    },
}

# ── Budget thresholds (configurable via env) ────────────
# Defaults: daily total > $100 alert, single user > $10/day alert
DEFAULT_DAILY_BUDGET_USD = 100.0
DEFAULT_USER_DAILY_BUDGET_USD = 10.0

# Slack webhook URL (set via env SLACK_WEBHOOK_URL)
SLACK_WEBHOOK_URL: Optional[str] = None


def get_pricing(model: str) -> dict[str, float]:
    """Get pricing for a given model, falling back to defaults."""
    return PRICING.get(model, PRICING["_default"])


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_prompt_tokens: int = 0,
) -> float:
    """Calculate USD cost from token counts.

    Args:
        model: Model name (e.g. "deepseek-chat")
        prompt_tokens: Number of input (prompt) tokens
        completion_tokens: Number of output (completion) tokens
        cached_prompt_tokens: Number of cached input tokens (75% discount)

    Returns:
        Cost in USD, rounded to 6 decimal places.
    """
    pricing = get_pricing(model)

    # Non-cached prompt tokens
    non_cached_prompt = max(0, prompt_tokens - cached_prompt_tokens)
    prompt_cost = (non_cached_prompt / 1000) * pricing.get("input_per_1k", 0.001)
    cached_cost = (cached_prompt_tokens / 1000) * pricing.get("cached_input_per_1k", pricing.get("input_per_1k", 0.001))
    completion_cost = (completion_tokens / 1000) * pricing.get("output_per_1k", 0.002)

    return round(prompt_cost + cached_cost + completion_cost, 6)


class LLMCostTracker:
    """Service for recording, querying, and alerting on LLM costs."""

    async def record(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Record a single LLM API call cost.

        This is called automatically by the LLM client wrapper
        (`DeepSeekLLM._complete()`).
        """
        total_tokens = prompt_tokens + completion_tokens
        try:
            record = LLMCost(
                user_id=user_id,
                project_id=project_id,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                metadata=metadata or {},
                request_id=request_id,
            )
            await record.insert()
            logger.debug(
                f"LLM cost recorded: {provider}/{model} "
                f"{total_tokens}toks ${cost_usd:.6f}"
            )
        except Exception as e:
            logger.warning(f"Failed to record LLM cost (non-fatal): {e}")

    async def get_daily_summary(
        self,
        day: Optional[datetime] = None,
    ) -> dict:
        """Get cost summary for a specific day (default: today).

        Returns:
            {
                "date": "2026-06-10",
                "total_usd": 1.23,
                "total_tokens": 50000,
                "total_calls": 42,
                "by_provider": {"deepseek": {"calls": 40, "cost_usd": 1.10, "tokens": 45000}},
                "by_model": {"deepseek-chat": {"calls": 35, "cost_usd": 0.80, "tokens": 40000}},
                "by_user": {"user_abc": {"calls": 10, "cost_usd": 0.50}},
                "top_users": [{"user_id": "user_abc", "cost_usd": 0.50, "calls": 10}],
            }
        """
        day = day or datetime.now(timezone.utc)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        records = await LLMCost.find(
            LLMCost.ts >= day_start,
            LLMCost.ts < day_end,
        ).to_list()

        if not records:
            return {
                "date": day_start.strftime("%Y-%m-%d"),
                "total_usd": 0.0,
                "total_tokens": 0,
                "total_calls": 0,
                "by_provider": {},
                "by_model": {},
                "by_user": {},
                "top_users": [],
            }

        total_calls = len(records)
        total_usd = sum(r.cost_usd for r in records)
        total_tokens = sum(r.total_tokens for r in records)

        by_provider: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        by_user: dict[str, dict] = {}

        for r in records:
            # By provider
            if r.provider not in by_provider:
                by_provider[r.provider] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_provider[r.provider]["calls"] += 1
            by_provider[r.provider]["cost_usd"] += r.cost_usd
            by_provider[r.provider]["tokens"] += r.total_tokens

            # By model
            if r.model not in by_model:
                by_model[r.model] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_model[r.model]["calls"] += 1
            by_model[r.model]["cost_usd"] += r.cost_usd
            by_model[r.model]["tokens"] += r.total_tokens

            # By user
            uid = r.user_id or "__system__"
            if uid not in by_user:
                by_user[uid] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_user[uid]["calls"] += 1
            by_user[uid]["cost_usd"] += r.cost_usd
            by_user[uid]["tokens"] += r.total_tokens

        # Round costs
        for d in [by_provider, by_model, by_user]:
            for v in d.values():
                v["cost_usd"] = round(v["cost_usd"], 4)

        # Top users by cost
        top_users = sorted(
            [{"user_id": uid, **stats} for uid, stats in by_user.items()],
            key=lambda x: x["cost_usd"],
            reverse=True,
        )[:10]

        return {
            "date": day_start.strftime("%Y-%m-%d"),
            "total_usd": round(total_usd, 4),
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "by_provider": by_provider,
            "by_model": by_model,
            "by_user": by_user,
            "top_users": top_users,
        }

    async def get_monthly_summary(
        self,
        year_month: Optional[str] = None,
    ) -> dict:
        """Get cost summary for a month.

        Args:
            year_month: "2026-06" format. Defaults to current month.

        Returns per-day breakdown + totals.
        """
        now = datetime.now(timezone.utc)
        ym = year_month or now.strftime("%Y-%m")
        year, month = int(ym.split("-")[0]), int(ym.split("-")[1])

        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        if month == 12:
            month_end = month_start.replace(year=year + 1, month=1)
        else:
            month_end = month_start.replace(month=month + 1)

        records = await LLMCost.find(
            LLMCost.ts >= month_start,
            LLMCost.ts < month_end,
        ).to_list()

        if not records:
            return {
                "month": ym,
                "total_usd": 0.0,
                "total_tokens": 0,
                "total_calls": 0,
                "daily": [],
                "by_provider": {},
                "by_model": {},
            }

        # Per-day aggregation
        daily: dict[str, dict] = {}
        by_provider: dict[str, dict] = {}
        by_model: dict[str, dict] = {}

        for r in records:
            day_key = r.ts.strftime("%Y-%m-%d")
            if day_key not in daily:
                daily[day_key] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            daily[day_key]["calls"] += 1
            daily[day_key]["cost_usd"] += r.cost_usd
            daily[day_key]["tokens"] += r.total_tokens

            if r.provider not in by_provider:
                by_provider[r.provider] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_provider[r.provider]["calls"] += 1
            by_provider[r.provider]["cost_usd"] += r.cost_usd
            by_provider[r.provider]["tokens"] += r.total_tokens

            if r.model not in by_model:
                by_model[r.model] = {"calls": 0, "cost_usd": 0.0, "tokens": 0}
            by_model[r.model]["calls"] += 1
            by_model[r.model]["cost_usd"] += r.cost_usd
            by_model[r.model]["tokens"] += r.total_tokens

        total_calls = len(records)
        total_usd = sum(r.cost_usd for r in records)
        total_tokens = sum(r.total_tokens for r in records)

        daily_list = sorted(
            [{"date": d, **stats} for d, stats in daily.items()],
            key=lambda x: x["date"],
        )

        for d in [by_provider, by_model]:
            for v in d.values():
                v["cost_usd"] = round(v["cost_usd"], 4)
        for d in daily_list:
            d["cost_usd"] = round(d["cost_usd"], 4)

        return {
            "month": ym,
            "total_usd": round(total_usd, 4),
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "daily": daily_list,
            "by_provider": by_provider,
            "by_model": by_model,
        }

    async def check_budget_alert(self, day: Optional[datetime] = None) -> Optional[str]:
        """Check if any budget thresholds are exceeded and send Slack alert.

        Returns:
            Alert message if threshold exceeded, otherwise None.
        """
        day = day or datetime.now(timezone.utc)
        summary = await self.get_daily_summary(day)

        if summary["total_calls"] == 0:
            return None

        daily_budget = (
            settings.LLM_COST_DAILY_BUDGET_USD
            if settings.LLM_COST_DAILY_BUDGET_USD is not None and settings.LLM_COST_DAILY_BUDGET_USD > 0
            else DEFAULT_DAILY_BUDGET_USD
        )
        user_budget = (
            settings.LLM_COST_USER_DAILY_BUDGET_USD
            if settings.LLM_COST_USER_DAILY_BUDGET_USD is not None and settings.LLM_COST_USER_DAILY_BUDGET_USD > 0
            else DEFAULT_USER_DAILY_BUDGET_USD
        )

        alerts: list[str] = []
        date_str = summary["date"]

        # Check total daily budget
        if summary["total_usd"] > daily_budget:
            msg = (
                f"🚨 *LLM Cost Alert — {date_str}*\n"
                f"Daily total *${summary['total_usd']:.2f}* exceeds budget "
                f"*${daily_budget:.2f}*\n"
                f"Calls: {summary['total_calls']} | Tokens: {summary['total_tokens']:,}"
            )
            alerts.append(msg)
            logger.warning(f"Daily LLM cost alert: ${summary['total_usd']:.2f} > ${daily_budget:.2f}")

        # Check per-user budgets
        for user_entry in summary.get("top_users", []):
            if user_entry["cost_usd"] > user_budget:
                msg = (
                    f"⚠️ *User Cost Alert — {date_str}*\n"
                    f"User `{user_entry['user_id'][:12]}...` spent "
                    f"*${user_entry['cost_usd']:.2f}* today (budget: ${user_budget:.2f})\n"
                    f"Calls: {user_entry['calls']}"
                )
                alerts.append(msg)
                logger.warning(
                    f"User LLM cost alert: {user_entry['user_id'][:12]} "
                    f"${user_entry['cost_usd']:.2f} > ${user_budget:.2f}"
                )

        # Send alerts to Slack
        slack_webhook = settings.SLACK_WEBHOOK_URL
        if alerts and slack_webhook:
            for alert_msg in alerts:
                await self._send_slack_alert(alert_msg, slack_webhook)

        return alerts[0] if alerts else None

    async def _send_slack_alert(self, message: str, webhook_url: str) -> None:
        """Send a formatted alert to Slack via webhook."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                payload = {
                    "text": message,
                    "mrkdwn": True,
                }
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code not in (200, 201, 204):
                    logger.warning(
                        f"Slack alert failed: {resp.status_code} — {resp.text[:200]}"
                    )
                else:
                    logger.info("Slack budget alert sent successfully")
        except Exception as e:
            logger.warning(f"Failed to send Slack alert (non-fatal): {e}")


# ── Singleton ───────────────────────────────────────────

cost_tracker = LLMCostTracker()
