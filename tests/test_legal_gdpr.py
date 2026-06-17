"""Smoke tests for legal + GDPR routes (TASK-010 + TASK-012).

Mongodb-dependent tests moved to tests/integration/test_legal_gdpr.py.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.legal import router as legal_router
from app.routes.gdpr import router as gdpr_router


class _StubUser:
    clerk_user_id = "user_test_001"
    email = "test@test.com"
    name = "Test User"
    tier = "free"


async def _fake_current_user():
    return _StubUser()


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(legal_router)
    app.include_router(gdpr_router)
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = _fake_current_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_invalid_slug_404(client):
    r = client.get("/api/v1/legal/nonexistent")
    assert r.status_code == 404
def test_pending_endpoint_requires_auth(app):
    """Without auth override, pending should 401."""
    # Build a fresh app without the auth override
    from app.auth import get_current_user
    fresh = FastAPI()
    fresh.include_router(legal_router)
    fresh.include_router(gdpr_router)
    c = TestClient(fresh)
    r = c.get("/api/v1/legal/pending")
    assert r.status_code == 401


def test_accept_legal_invalid_body(client):
    r = client.post("/api/v1/legal/accept", json={})
    assert r.status_code == 400


def test_accept_legal_invalid_slug(client):
    r = client.post("/api/v1/legal/accept", json={
        "acceptances": [{"slug": "bogus", "version": "1.0.0"}],
    })
    assert r.status_code == 400


# ── GDPR tests ─────────────────────────────────────────


def test_post_consent_invalid_body(client):
    r = client.post("/api/v1/users/me/consents", json={})
    assert r.status_code == 400

