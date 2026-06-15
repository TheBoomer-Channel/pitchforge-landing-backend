"""Tests for usage tracker — TASK-019."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.usage import router as usage_router


class _StubUser:
    clerk_user_id = "user_test"
    email = "[email protected]"
    name = "Test"
    tier = "free"
    trial_started_at = None
    trial_ends_at = None
    trial_extended = False
    async def save(self): pass


async def _fake_current_user():
    return _StubUser()


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(usage_router)
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = _fake_current_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_usage_status_returns_metrics(client):
    r = client.get("/api/v1/usage/status")
    assert r.status_code == 200
    body = r.json()
    for metric in ["research_call", "llm_token_in", "llm_token_out", "pdf_export", "api_call"]:
        assert metric in body, f"Missing {metric} in response"
        assert "current" in body[metric]
        assert "soft_cap" in body[metric]
        assert "hard_cap" in body[metric]
        assert "pct" in body[metric]


def test_usage_limits_returns_caps(client):
    r = client.get("/api/v1/usage/limits")
    assert r.status_code == 200


def test_usage_history_empty(client):
    r = client.get("/api/v1/usage/history")
    assert r.status_code == 200
    body = r.json()
    assert "month" in body
    assert "metrics" in body


def test_usage_history_with_bad_metric(client):
    r = client.get("/api/v1/usage/history?metric=nonexistent")
    assert r.status_code == 400


def test_push_to_stripe_requires_secret(client):
    r = client.post("/api/v1/usage/push-to-stripe")
    assert r.status_code == 401


def test_tracker_get_by_tier_free():
    from app.services.usage_tracker import tracker
    caps = tracker.get_by_tier("free")
    assert len(caps) == 5


def test_tier_caps_defined_for_all():
    """All tiers should have all 5 metrics defined."""
    from app.services.usage_tracker import TIER_CAPS
    from app.models.usage import METRICS
    for tier, metrics in TIER_CAPS.items():
        for m in METRICS:
            assert m in metrics, f"Tier {tier} missing metric {m}"
