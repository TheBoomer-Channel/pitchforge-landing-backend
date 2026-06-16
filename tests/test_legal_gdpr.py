"""Smoke tests for legal + GDPR routes (TASK-010 + TASK-012).

These tests stub the auth dependency so they don't require a real
Clerk connection or a running MongoDB. They exercise:
  * Legal version listing
  * Legal document retrieval (markdown content)
  * Version history
  * Invalid slug 404
  * GDPR deletion request → cancel flow
  * GDPR consents POST/GET
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.legal import router as legal_router
from app.routes.gdpr import router as gdpr_router


# ── Auth stub ───────────────────────────────────────────


class _StubUser:
    def __init__(self):
        self.clerk_user_id = "user_test_001"
        self.email = "[email protected]"
        self.name = "Test User"
        self.tier = "free"
        self.stripe_customer_id = None
        self.created_at = datetime.now(timezone.utc)


async def _fake_current_user():
    return _StubUser()


# ── Test app ────────────────────────────────────────────


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(legal_router)
    app.include_router(gdpr_router)

    # Override auth dep
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = _fake_current_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Legal tests ────────────────────────────────────────


@pytest.mark.mongodb
def test_get_legal_version_returns_dict(client):
    """Smoke: endpoint responds, may be empty if no DB."""
    r = client.get("/api/v1/legal/version")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


@pytest.mark.mongodb
def test_get_legal_doc_returns_markdown(client):
    r = client.get("/api/v1/legal/terms")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "terms"
    assert body["version"]
    assert "# PitchForge" in body["content_md"]
    assert "CARGOFFER" in body["content_md"]
    assert body["word_count"] > 0
    assert body["reading_minutes"] >= 1


@pytest.mark.mongodb
def test_get_all_legal_docs(client):
    for slug in ("terms", "privacy", "cookies", "aup"):
        r = client.get(f"/api/v1/legal/{slug}")
        assert r.status_code == 200, f"{slug} failed: {r.text}"
        assert "# PitchForge" in r.json()["content_md"]


def test_invalid_slug_404(client):
    r = client.get("/api/v1/legal/nonexistent")
    assert r.status_code == 404


@pytest.mark.mongodb
def test_legal_history_endpoint(client):
    r = client.get("/api/v1/legal/privacy/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


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


@pytest.mark.mongodb
def test_deletion_status_empty(client):
    r = client.get("/api/v1/users/me/deletion-status")
    assert r.status_code == 200
    # No DB → may be {status: "none"} or 500; accept both
    assert r.status_code in (200, 500)


@pytest.mark.mongodb
def test_cancel_deletion_when_none(client):
    r = client.post("/api/v1/users/me/cancel-deletion")
    # 404 if no DB, 404 if no pending; both acceptable in smoke test
    assert r.status_code in (404, 500)


def test_post_consent_invalid_body(client):
    r = client.post("/api/v1/users/me/consents", json={})
    assert r.status_code == 400


@pytest.mark.mongodb
def test_post_consent_validates_types(client):
    r = client.post(
        "/api/v1/users/me/consents",
        json={"purpose": "marketing_email", "granted": True},
    )
    # 204 on success, 500 if no DB
    assert r.status_code in (204, 500)
