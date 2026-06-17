"""Integration tests for legal documents + GDPR — TASK-010 + TASK-012.

Legal document endpoints (/version, /{slug}, /{slug}/history) are PUBLIC
(no Depends(get_current_user)), so they work without auth headers.

GDPR endpoints require auth — use Bearer token for dev-mode auto-user creation.
"""

from __future__ import annotations

import pytest


# ── Legal doc tests (PUBLIC endpoints) ──────────────────

@pytest.mark.asyncio
async def test_get_legal_version_returns_dict(client):
    """GET /version returns a dict of slug→version for current docs."""
    r = await client.get("/api/v1/legal/version")
    assert r.status_code == 200, f"Version failed: {r.text}"
    assert isinstance(r.json(), dict)


@pytest.mark.asyncio
async def test_get_legal_doc_returns_markdown(client):
    """GET /terms returns slug, version, content_md with expected text."""
    r = await client.get("/api/v1/legal/terms")
    assert r.status_code == 200, f"Terms failed: {r.text}"
    body = r.json()
    assert body["slug"] == "terms"
    assert body["version"]
    assert "CARGOFFER" in body["content_md"]
    assert body["word_count"] > 0
    assert body["reading_minutes"] >= 1


@pytest.mark.asyncio
async def test_get_all_legal_docs(client):
    """All 4 legal slugs should return 200 with markdown content."""
    for slug in ("terms", "privacy", "cookies", "aup"):
        r = await client.get(f"/api/v1/legal/{slug}")
        assert r.status_code == 200, f"{slug} failed: {r.text}"
        assert "CARGOFFER" in r.json()["content_md"]


@pytest.mark.asyncio
async def test_legal_history_endpoint(client):
    """GET /privacy/history should return a list of version entries."""
    r = await client.get("/api/v1/legal/privacy/history")
    assert r.status_code == 200, f"History failed: {r.text}"
    assert isinstance(r.json(), list)


# ── GDPR tests (AUTH required) ──────────────────────────

@pytest.mark.asyncio
async def test_deletion_status_empty(client, auth_headers):
    """Fresh user should have deletion status 'none'."""
    r = await client.get("/api/v1/users/me/deletion-status", headers=auth_headers)
    assert r.status_code == 200, f"Deletion status failed: {r.text}"
    body = r.json()
    assert body["status"] == "none"


@pytest.mark.asyncio
async def test_cancel_deletion_when_none(client, auth_headers):
    """Cancelling when no deletion is pending should return 404."""
    r = await client.post(
        "/api/v1/users/me/cancel-deletion",
        headers=auth_headers,
    )
    assert r.status_code == 404, (
        f"Expected 404 for cancel with no pending, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_post_consent_validates_types(client, auth_headers):
    """POST /consents with valid body should return 204."""
    r = await client.post(
        "/api/v1/users/me/consents",
        json={"purpose": "marketing_email", "granted": True},
        headers=auth_headers,
    )
    assert r.status_code == 204, (
        f"Expected 204 for valid consent, got {r.status_code}: {r.text}"
    )
