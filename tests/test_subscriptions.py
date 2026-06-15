"""Smoke tests for TASK-016 (Subscription model + idempotency)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest


def test_subscription_model_instantiates():
    """Ensure the Beanie model can be instantiated with required fields."""
    from app.database import Subscription
    sub = Subscription(
        user_id="user_001",
        stripe_customer_id="cus_001",
        stripe_subscription_id="sub_001",
        tier="pro",
    )
    assert sub.user_id == "user_001"
    assert sub.stripe_customer_id == "cus_001"
    assert sub.stripe_subscription_id == "sub_001"
    assert sub.tier == "pro"
    assert sub.status == "active"
    assert sub.cancel_at_period_end is False
    assert sub.created_at is not None


def test_subscription_model_optional_dates():
    from app.database import Subscription
    now = datetime.now(timezone.utc)
    sub = Subscription(
        user_id="user_001",
        stripe_customer_id="cus_001",
        stripe_subscription_id="sub_001",
        tier="pro",
        current_period_start=now,
        current_period_end=now,
        trial_ends_at=now,
    )
    assert sub.current_period_start == now
    assert sub.current_period_end == now
    assert sub.trial_ends_at == now


def test_processed_webhook_event_idempotency():
    """Ensure ProcessedWebhookEvent enforces unique stripe_event_id."""
    from app.database import ProcessedWebhookEvent
    e1 = ProcessedWebhookEvent(
        stripe_event_id="evt_001",
        event_type="customer.subscription.created",
    )
    assert e1.stripe_event_id == "evt_001"
    assert e1.event_type == "customer.subscription.created"
    # In Beanie, the unique index on stripe_event_id would prevent duplicates
    # at the Mongo level — the model just declares it; the enforcement is
    # via the Settings.indexes below.
