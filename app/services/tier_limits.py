"""Tier Limits Service — reads usage limits from Stripe product metadata.

Uses MongoDB User document for per-user counters.
"""

import logging
from datetime import date, datetime, timezone

import stripe

from ..config import settings
from ..database import User

logger = logging.getLogger(__name__)

DEFAULT_LIMITS: dict[str, dict] = {
    "free": {"max_tokens": 2000, "max_research_per_day": 1, "max_projects_per_month": 3},
    "starter": {"max_tokens": 10000, "max_research_per_day": 5, "max_projects_per_month": 15},
    "pro": {"max_tokens": 50000, "max_research_per_day": 20, "max_projects_per_month": 50},
    "code_mvp": {"max_tokens": 100000, "max_research_per_day": 50, "max_projects_per_month": 100},
}


class TierLimits:
    """Tier limit utilities — resolving limits from Stripe metadata or defaults."""

    @staticmethod
    def get_tier_limits(tier: str) -> dict:
        if hasattr(settings, "TIER_LIMITS") and tier in settings.TIER_LIMITS:
            return settings.TIER_LIMITS[tier]
        return DEFAULT_LIMITS.get(tier, DEFAULT_LIMITS["free"])

    @staticmethod
    async def refresh_from_stripe() -> dict:
        if not settings.STRIPE_API_KEY:
            return DEFAULT_LIMITS
        try:
            stripe.api_key = settings.STRIPE_API_KEY
            products = stripe.Product.list(limit=50, active=True)
            for p in products.data:
                meta = dict(p.metadata or {})
                tier = meta.get("tier")
                if tier and tier in DEFAULT_LIMITS:
                    settings.TIER_LIMITS[tier] = {
                        "max_tokens": int(meta.get("max_tokens", DEFAULT_LIMITS[tier]["max_tokens"])),
                        "max_research_per_day": int(meta.get("max_research_per_day", DEFAULT_LIMITS[tier]["max_research_per_day"])),
                        "max_projects_per_month": int(meta.get("max_projects_per_month", DEFAULT_LIMITS[tier]["max_projects_per_month"])),
                    }
            return settings.TIER_LIMITS
        except Exception as e:
            logger.warning(f"Failed to fetch Stripe limits: {e}")
            return DEFAULT_LIMITS

    @staticmethod
    async def check_research_limit(user: User) -> dict:
        limits = TierLimits.get_tier_limits(user.tier)
        max_per_day = limits["max_research_per_day"]
        today = date.today()

        if user.last_research_date:
            last_date = _to_date(user.last_research_date)
            if last_date != today:
                user.research_count_today = 0
                user.last_research_date = datetime.now(timezone.utc)
                await user.save()

        if user.research_count_today >= max_per_day:
            return {"allowed": False, "reason": f"Daily research limit reached ({max_per_day}/day). Upgrade your plan.", "used": user.research_count_today, "limit": max_per_day}

        return {"allowed": True, "reason": "", "used": user.research_count_today, "limit": max_per_day}

    @staticmethod
    async def check_project_limit(user: User) -> dict:
        limits = TierLimits.get_tier_limits(user.tier)
        max_per_month = limits["max_projects_per_month"]
        if user.projects_this_month >= max_per_month:
            return {"allowed": False, "reason": f"Monthly project limit reached ({max_per_month}/month). Upgrade your plan.", "used": user.projects_this_month, "limit": max_per_month}
        return {"allowed": True, "reason": "", "used": user.projects_this_month, "limit": max_per_month}

    @staticmethod
    async def increment_research_count(user: User) -> None:
        today = date.today()
        if user.last_research_date:
            last_date = _to_date(user.last_research_date)
            if last_date != today:
                user.research_count_today = 0
        user.research_count_today += 1
        user.last_research_date = datetime.now(timezone.utc)
        await user.save()

    @staticmethod
    async def increment_project_count(user: User) -> None:
        user.projects_this_month += 1
        await user.save()

    @staticmethod
    async def get_tier_summary(user: User) -> dict:
        limits = TierLimits.get_tier_limits(user.tier)
        from .token_service import TokenService
        token_balance = await TokenService.get_token_balance(user.id)
        token_limit = limits["max_tokens"]
        today = date.today()
        research_reset = False
        if user.last_research_date:
            last_date = _to_date(user.last_research_date)
            if last_date != today:
                research_reset = True
        return {
            "id": str(user.id),
            "tier": user.tier,
            "limits": {
                "tokens": {"used": max(0, token_limit - token_balance), "limit": token_limit},
                "research_per_day": {"used": user.research_count_today if not research_reset else 0, "limit": limits["max_research_per_day"]},
                "projects_per_month": {"used": user.projects_this_month, "limit": limits["max_projects_per_month"]},
            },
            "token_balance": token_balance,
        }


def _to_date(dt) -> date:
    if hasattr(dt, 'date'):
        return dt.date()
    return dt if isinstance(dt, date) else date.today()
