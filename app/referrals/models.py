"""Referral model — TASK-042.

Tracks referral relationships: who referred whom, conversion status, and reward grants.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from beanie import Document, Indexed
from pydantic import Field


class Referral(Document):
    """A referral relationship between two users.

    Created when a new user signs up with ?ref=CODE.
    Updated when the referee becomes a paid user (via Stripe webhook).
    """

    referrer_id: Indexed(str)  # Clerk user ID of the referrer
    referee_id: Indexed(str, unique=True)  # Clerk user ID of the referee (one referrer per user)
    referral_code_used: str  # The code the referee used to sign up
    status: str = "pending"  # pending / signed_up / converted / reward_granted
    signed_up_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    converted_at: datetime | None = None  # When referee became a paid user
    reward_granted: bool = False
    reward_granted_at: datetime | None = None
    reward_type: str | None = None  # "free_month" / "credit" / "coupon"
    reward_details: dict = Field(default_factory=dict)

    class Settings:
        name = "referrals"
        indexes = [
            "referrer_id",
            "referee_id",
            "referral_code_used",
            [("referrer_id", 1), ("status", 1)],
            [("referrer_id", 1), ("reward_granted", 1)],
        ]
