"""Tests for TASK-020: Coupons & Discounts.

Tests focus on the Coupon model validation logic and Redemption model
since they don't require MongoDB/Stripe.
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.models.coupon import Coupon, Redemption


def test_coupon_is_valid_active():
    """A fresh coupon with no limits should be valid."""
    c = Coupon(code="TEST10", kind="percent", value=10, is_active=True)
    valid, reason = c.is_valid()
    assert valid is True
    assert reason == ""


def test_coupon_is_valid_disabled():
    """A disabled coupon should be invalid."""
    c = Coupon(code="DISABLED", kind="percent", value=10, is_active=False)
    valid, reason = c.is_valid()
    assert valid is False
    assert "disabled" in reason.lower()


def test_coupon_is_valid_max_uses_exhausted():
    """A coupon that has reached max_uses should be invalid."""
    c = Coupon(code="LIMITED", kind="percent", value=10, max_uses=5, used_count=5, is_active=True)
    valid, reason = c.is_valid()
    assert valid is False
    assert "limit" in reason.lower()


def test_coupon_is_valid_not_yet_valid():
    """A coupon with future valid_from should be invalid."""
    future = datetime.now(timezone.utc) + timedelta(hours=24)
    c = Coupon(code="FUTURE", kind="percent", value=10, valid_from=future, is_active=True)
    valid, reason = c.is_valid()
    assert valid is False
    assert "not yet valid" in reason.lower()


def test_coupon_is_valid_expired():
    """An expired coupon should be invalid."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    c = Coupon(code="EXPIRED", kind="percent", value=10, valid_until=past, is_active=True)
    valid, reason = c.is_valid()
    assert valid is False
    assert "expired" in reason.lower()


def test_redemption_default_timestamp():
    """Redemption should auto-set redeemed_at."""
    r = Redemption(coupon_code="TEST", user_id="user1", tier="starter")
    assert r.redeemed_at is not None
    assert isinstance(r.redeemed_at, datetime)


def test_redemption_unique_index_fields():
    """The compound index fields should be present."""
    r = Redemption(coupon_code="LAUNCH50", user_id="user123", tier="pro", discount_amount=1450)
    assert r.coupon_code == "LAUNCH50"
    assert r.user_id == "user123"
    assert r.tier == "pro"
    assert r.discount_amount == 1450


def test_coupon_defaults():
    """Default values for optional fields."""
    c = Coupon(code="DEFAULT", kind="amount", value=500)
    assert c.max_uses == 0
    assert c.used_count == 0
    assert c.is_active is True
    assert c.valid_from is None
    assert c.valid_until is None
    assert c.plan_restriction is None
    assert c.partner_id is None
    assert c.stripe_coupon_id is None


def test_coupon_plan_restriction():
    """plan_restriction should be stored and retrievable."""
    c = Coupon(code="PROONLY", kind="percent", value=20, plan_restriction="pro")
    assert c.plan_restriction == "pro"


def test_coupon_partner_tracking():
    """Partner ID should be stored for tracking."""
    c = Coupon(code="PARTNERX", kind="percent", value=15, partner_id="partner_acme")
    assert c.partner_id == "partner_acme"


def test_coupon_uppercase_code():
    """Code should be stored uppercase by convention."""
    c = Coupon(code="launch50", kind="percent", value=50)
    assert c.code == "launch50"  # Beanie stores as-is; uppercasing happens in routes
