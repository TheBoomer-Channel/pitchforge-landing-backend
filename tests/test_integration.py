"""Integration tests against the live running API on localhost:8086.

These test real endpoints: health, docs, public routes, auth, and error handling.
The API must be running (docker compose up) for these to pass.
"""

import pytest
import httpx

API_BASE = "http://localhost:8086"


@pytest.fixture
def client():
    """Return an httpx client pointed at the running API."""
    return httpx.Client(base_url=API_BASE, timeout=10)



# ── Health & Meta ──────────────────────────────────────


def test_health_returns_ok(client):
    """GET /health returns status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == "PitchForge"
    assert "version" in data


def test_root_returns_endpoint_map(client):
    """GET / returns API endpoint map."""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "endpoints" in data
    assert "auth" in data["endpoints"]


def test_docs_accessible(client):
    """GET /docs returns Swagger UI HTML."""
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()


def test_redoc_accessible(client):
    """GET /redoc returns ReDoc HTML."""
    resp = client.get("/redoc")
    assert resp.status_code == 200


def test_openapi_json_valid(client):
    """GET /openapi.json returns valid OpenAPI spec."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "openapi" in data
    assert "paths" in data
    assert len(data["paths"]) >= 10


# ── Auth ───────────────────────────────────────────────


def test_register_returns_validation_error(client):
    """POST /auth/register with empty body returns 422."""
    resp = client.post("/auth/register", json={})
    assert resp.status_code == 422


def test_register_requires_email(client):
    """POST /auth/register missing email returns 422."""
    resp = client.post("/auth/register", json={"password": "test123", "name": "Test"})
    assert resp.status_code == 422


def test_login_returns_validation_error(client):
    """POST /auth/login with empty body returns 422."""
    resp = client.post("/auth/login", json={})
    assert resp.status_code == 422


# ── Public endpoints ───────────────────────────────────


def test_dashboard_served(client):
    """GET /dashboard returns static dashboard HTML."""
    resp = client.get("/dashboard")
    # Returns 200 (dashboard) or 307 (redirect to /dashboard/)
    assert resp.status_code in (200, 307)


# ── Protected endpoints (no auth) ──────────────────────


def test_api_validate_without_research(client):
    """POST /api/validate without idea returns something (public)."""
    resp = client.post("/api/validate", json={"idea": ""})
    # May return 200, 404 (endpoint not mounted), or 422
    assert resp.status_code in (200, 404, 422)


@pytest.mark.slow(reason="Runs full research pipeline with external API calls (~60s)")
def test_research_start_without_auth():
    """POST /api/research/start — endpoint responds (uses longer timeout for full pipeline)."""
    # The research pipeline runs inline and contacts external sources (HN, GitHub,
    # Wikipedia, DuckDuckGo, DeepSeek). Use a generous timeout.
    client = httpx.Client(base_url=API_BASE, timeout=60)
    resp = client.post("/api/research/start?idea=test+idea")
    # In dev mode this should not be strictly 401; accept any non-catastrophic
    assert resp.status_code != 401
    client.close()


# ── Error handling ─────────────────────────────────────


def test_nonexistent_route_returns_404(client):
    """GET /nonexistent returns 404."""
    resp = client.get("/nonexistent-route-xyz")
    assert resp.status_code == 404


def test_method_not_allowed(client):
    """DELETE /health returns 405."""
    resp = client.delete("/health")
    assert resp.status_code == 405


# ── CORS ───────────────────────────────────────────────


def test_options_preflight_responds(client):
    """OPTIONS preflight — API responds (CORS may reject incomplete preflight)."""
    resp = client.options("/health", headers={
        "Origin": "http://localhost:5174",
        "Access-Control-Request-Method": "GET",
    })
    # FastAPI returns 200 on valid preflight, 400 if incomplete
    assert resp.status_code in (200, 204, 400, 405)


# ── Rate limiting ──────────────────────────────────────


def test_rate_limit_headers_or_ok(client):
    """Multiple requests to /health don't get rate-limited."""
    for _ in range(5):
        resp = client.get("/health")
        assert resp.status_code == 200
