"""Integration test fixtures — run against a live API server.

Requires the Docker API container to be running with CLERK_SECRET_KEY unset
(dev mode — any Bearer token becomes a user ID).

Usage:
    docker compose up -d api mongodb redis
    CLERK_SECRET_KEY="" docker compose up -d api
    pytest tests/integration/ -v
"""

from __future__ import annotations

import uuid
import pytest
import httpx

API_URL = "http://localhost:8086"


@pytest.fixture
def unique_user_id():
    """Session-scoped unique user ID for test isolation.

    All integration tests in the session share the same test user,
    which is created on first authenticated request via dev-mode auth.
    """
    return f"test-integration-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def auth_headers(unique_user_id):
    """Bearer token that auto-creates a user in dev mode (no CLERK_SECRET_KEY).

    auth.py verify_clerk_token() returns the token itself as user ID
    when CLERK_SECRET_KEY is empty, and get_or_create_user() creates the user.
    """
    return {"Authorization": f"Bearer {unique_user_id}"}


@pytest.fixture
def cron_headers():
    """Headers for cron-secured endpoints (uses default dev secret)."""
    return {"X-Cron-Secret": "dev-cron-secret-change-in-prod"}


@pytest.fixture
async def client():
    """Async HTTP client targeting the live Docker API."""
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as ac:
        yield ac


@pytest.fixture(scope="session", autouse=True)
async def _skip_if_api_down():
    """Skip all integration tests if the API container is not reachable.

    Session-scoped (runs once) with proper async context manager.
    """
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as ac:
            r = await ac.get("/health")
        if r.status_code != 200:
            pytest.skip(f"API not healthy (status={r.status_code})")
    except Exception as e:
        pytest.skip(f"API not reachable at {API_URL}: {e}")
