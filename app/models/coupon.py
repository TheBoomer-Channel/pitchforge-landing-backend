"""Coupon & Redemption models — discount codes for subscriptions and one-time purchases.

Each coupon can be either a percentage discount or a fixed amount off.
Supports optional plan_restriction, max_uses, valid_from/valid_until, and partner tracking.
"""

from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


class Coupon(Document):
    """A discount code that can be applied at checkout.

    Fields:
        code: Human-readable coupon code (case-insensitive, stored uppercase).
        kind: 'percent' or 'amount'.
        value: Discount value — percentage points (e.g. 20 for 20% off)
               or amount in cents (e.g. 1000 for €10 off).
        max_uses: Maximum number of times the coupon can be used (0 = unlimited).
        used_count: Number of times the coupon has been used (atomic increment).
        valid_from: Start of validity period (None = no start limit).
        valid_until: End of validity period (None = no expiry).
        plan_restriction: Optional tier slug this coupon applies to.
                          Only valid for this tier. None = any tier.
        partner_id: Optional partner/affiliate identifier for tracking.
        is_active: Soft toggle to disable a coupon without deleting it.
        stripe_coupon_id: ID of the corresponding Stripe coupon (synced).
        created_at: Auto-set on creation.
        updated_at: Updated on modification.
    """

    code: Indexed(str, unique=True)  # Stored uppercase for case-insensitive lookups
    kind: str  # 'percent' or 'amount'
    value: int  # percentage points (1-100) or amount in cents
    max_uses: int = 0  # 0 = unlimited
    used_count: int = 0
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    plan_restriction: Optional[str] = None  # tier slug: starter / pro / code_mvp
    partner_id: Optional[str] = None
    is_active: bool = True
    stripe_coupon_id: Optional[str] = None  # Synced Stripe coupon ID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

    class Settings:
        name = "coupons"
        indexes = [
            "code",
            [("is_active", 1), ("valid_until", 1)],
            "partner_id",
        ]

    async def is_valid(self) -> tuple[bool, str]:
        """Check whether the coupon is currently valid.

        Returns (True, "") or (False, reason_string).
        """
        now = datetime.now(timezone.utc)

        if not self.is_active:
            return False, "Coupon is disabled"

        if self.max_uses > 0 and self.used_count >= self.max_uses:
            return False, "Coupon has reached its usage limit"

        if self.valid_from and now < self.valid_from:
            return False, "Coupon is not yet valid"

        if self.valid_until and now > self.valid_until:
            return False, "Coupon has expired"

        return True, ""

    async def increment_use(self) -> None:
        """Atomically increment the used_count via MongoDB $inc."""
        from ..config import settings
        from ..database import client
        if client is not None:
            col = client[settings.MONGODB_DB_NAME]["coupons"]
            await col.update_one(
                {"_id": self.id},
                {"$inc": {"used_count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            )
        self.used_count = (self.used_count or 0) + 1


class Redemption(Document):
    """Tracks each time a coupon is redeemed by a user.

    One row per (coupon_code, user_id) — each user can only use a
    coupon once, enforced by a unique compound index.
    """

    coupon_code: str
    user_id: Indexed(str)
    tier: str  # The tier purchased when this coupon was used
    stripe_session_id: Optional[str] = None  # The Stripe checkout session
    stripe_coupon_id: Optional[str] = None
    discount_amount: int = 0  # Amount discounted in cents
    redeemed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "redemptions"
        indexes = [
            [("coupon_code", 1), ("user_id", 1)],  # unique compound — one use per user per coupon
            "user_id",
            "coupon_code",
        ]
