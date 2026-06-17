"""Smoke tests for TASK-018 (Free trial) — cron endpoint only.

Mongodb-dependent tests moved to tests/integration/test_trial.py.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.trial import router as trial_router


class _StubUser:
    clerk_user_id = "user_test"
    email = "test@test.com"
    name = "Test"
    tier = "free"


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


def test_cron_requires_secret(client):
    r = client.post("/api/v1/trial/cron-daily")
    assert r.status_code == 401


@pytest.mark.skip(reason="Moved to tests/integration/test_trial.py — run with pytest tests/integration/")
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
