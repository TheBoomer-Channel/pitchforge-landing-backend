"""Integration tests for usage tracker endpoints — TASK-019.

Run against live Docker API with dev-mode auth.
"""

from __future__ import annotations

import pytest

REQUIRED_METRICS = [
    "research_call",
    "llm_token_in",
    "llm_token_out",
    "pdf_export",
    "api_call",
]


@pytest.mark.asyncio
async def test_usage_status_returns_metrics(client, auth_headers):
    """GET /status should return all 5 metered metrics with caps."""
    r = await client.get("/api/v1/usage/status", headers=auth_headers)
    assert r.status_code == 200, f"Status failed: {r.text}"
    body = r.json()
    for metric in REQUIRED_METRICS:
        assert metric in body, f"Missing {metric} in response"
        assert "current" in body[metric], f"{metric} missing 'current'"
        assert "soft_cap" in body[metric], f"{metric} missing 'soft_cap'"
        assert "hard_cap" in body[metric], f"{metric} missing 'hard_cap'"
        assert "pct" in body[metric], f"{metric} missing 'pct'"


@pytest.mark.asyncio
async def test_usage_history_empty(client, auth_headers):
    """GET /history for fresh user should return month + metrics keys."""
    r = await client.get("/api/v1/usage/history", headers=auth_headers)
    assert r.status_code == 200, f"History failed: {r.text}"
    body = r.json()
    assert "month" in body
    assert "metrics" in body
