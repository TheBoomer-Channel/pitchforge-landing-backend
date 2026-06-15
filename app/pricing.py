"""Shared pricing constants — tier → Stripe price ID and amount mapping.

Extracted from checkout.py to avoid circular imports with coupons.py.
"""

from .config import settings

# ── Tier → Stripe price mapping ────────────────────────

PRICE_MAP = {
    "starter": settings.PRICE_STARTER,
    "pro": settings.PRICE_PRO,
    "code_mvp": settings.PRICE_CODE_MVP,
}

AMOUNT_MAP = {
    "starter": 900,        # €9
    "pro": 2900,           # €29
    "code_mvp": 49900,     # €499
}
