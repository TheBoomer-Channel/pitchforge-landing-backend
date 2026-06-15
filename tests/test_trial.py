"""Smoke tests for TASK-018 (Free trial) — status + cron endpoints."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.trial import router as trial_router


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
    app.include_router(trial_router)
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = _fake_current_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_trial_status_no_trial(client):
    r = client.get("/api/v1/trial/status")
    assert r.status_code == 200
    body = r.json()
    assert body["in_trial"] is False
    assert body["days_remaining"] == 0
    assert body["effective_tier"] == "free"


def test_trial_status_in_trial(client, monkeypatch):
    user = _StubUser()
    now = datetime.now(timezone.utc)
    user.trial_started_at = now - timedelta(days=5)
    user.trial_ends_at = now + timedelta(days=9)
    user.tier = "pro"

    async def _get_user():
        return user
    monkeypatch.setattr("app.routes.trial.get_current_user", _get_user)

    r = client.get("/api/v1/trial/status")
    assert r.status_code == 200
    body = r.json()
    assert body["in_trial"] is True
    assert body["days_remaining"] >= 8


def test_start_trial_idempotent(client, monkeypatch):
    user = _StubUser()
    user.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=5)

    async def _get_user():
        return user
    monkeypatch.setattr("app.routes.trial.get_current_user", _get_user)

    r = client.post("/api/v1/trial/start")
    # Idempotent: 200, already_trialed=True
    assert r.status_code == 200
    body = r.json()
    assert body["already_trialed"] is True


def test_cron_requires_secret(client):
    r = client.post("/api/v1/trial/cron-daily")
    assert r.status_code == 401


def test_cron_with_secret_works(client, monkeypatch):
    import os
    monkeypatch.setenv("TRIAL_CRON_SECRET", "test-secret-123")
    # Re-import the constant
    import importlib
    import app.routes.trial as t
    importlib.reload(t)
    # Rebuild the app with the reloaded module
    app = FastAPI()
    app.include_router(t.router)
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = _fake_current_user
    c = TestClient(app)
    r = c.post("/api/v1/trial/cron-daily", headers={"X-Cron-Secret": "test-secret-123"})
    assert r.status_code == 200
    body = r.json()
    assert "expired_trials" in body
    assert "emails_sent" in body
    assert "ran_at" in body
