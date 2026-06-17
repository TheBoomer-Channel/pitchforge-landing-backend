"""Integration tests for trial endpoints — TASK-018.

Run against live Docker API with dev-mode auth (no Clerk required).
Each test uses a unique Bearer token that auto-creates a user via
get_or_create_user() when CLERK_SECRET_KEY is empty.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_trial_status_no_trial(client, auth_headers):
    """Fresh user should show in_trial=False with effective_tier=free."""
    r = await client.get("/api/v1/trial/status", headers=auth_headers)
    assert r.status_code == 200, f"Unexpected: {r.text}"
    body = r.json()
    assert body["in_trial"] is False
    assert body["days_remaining"] == 0
    assert body["effective_tier"] == "free"


@pytest.mark.asyncio
async def test_trial_status_in_trial(client, auth_headers):
    """After starting a trial, status should show in_trial=True."""
    # Start the trial first
    r = await client.post("/api/v1/trial/start", headers=auth_headers)
    assert r.status_code == 200, f"Start failed: {r.text}"
    start_body = r.json()
    assert start_body["trial_started"] is True

    # Now check status
    r = await client.get("/api/v1/trial/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["in_trial"] is True
    assert body["days_remaining"] >= 13  # 14-day trial just started


@pytest.mark.asyncio
async def test_start_trial_idempotent(client, auth_headers):
    """Second call to /start should return already_trialed=True."""
    # First call starts trial
    r = await client.post("/api/v1/trial/start", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["trial_started"] is True

    # Second call is idempotent — does not extend
    r = await client.post("/api/v1/trial/start", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["already_trialed"] is True
    assert body["trial_started"] is False


@pytest.mark.asyncio
async def test_cron_with_secret_works(client, cron_headers):
    """Cron endpoint should return expired_trials + emails_sent counts."""
    r = await client.post("/api/v1/trial/cron-daily", headers=cron_headers)
    assert r.status_code == 200, f"Cron failed: {r.text}"
    body = r.json()
    assert "expired_trials" in body
    assert "emails_sent" in body
    assert "ran_at" in body
