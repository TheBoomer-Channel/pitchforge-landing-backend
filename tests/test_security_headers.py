"""Tests for security headers middleware and CSP report endpoint.

Covers:
  * All defensive headers present on a sample response
  * CSP includes the per-request nonce placeholder is rendered
  * WS upgrade paths still get HSTS but no CSP (avoids breaking the WS handshake)
  * CSP report endpoint accepts both legacy and modern envelopes
  * SECURITY_HEADERS_ENABLED=false bypasses the middleware
"""

from __future__ import annotations

import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security_headers import (
    SecurityHeadersMiddleware,
    HSTS_VALUE,
    get_csp_nonce,
)
from app.routes.csp_report import router as csp_router


# ── Fixtures ───────────────────────────────────────────


@pytest.fixture
def app_with_headers():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/")
    async def root():
        return {"ok": True}

    @app.get("/api/v1/ping")
    async def ping():
        return {"pong": True}

    @app.get("/ws/test")
    async def ws_test():
        return {"ws": True}

    app.include_router(csp_router)
    return app


@pytest.fixture
def client(app_with_headers):
    return TestClient(app_with_headers)


# ── Header presence ────────────────────────────────────


def test_hsts_header_present(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("strict-transport-security") == HSTS_VALUE


def test_x_frame_options_denied(client):
    r = client.get("/")
    assert r.headers.get("x-frame-options") == "DENY"


def test_x_content_type_options_nosniff(client):
    r = client.get("/")
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_referrer_policy(client):
    r = client.get("/")
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_permissions_policy_disables_features(client):
    r = client.get("/")
    pp = r.headers.get("permissions-policy", "")
    for feature in ("camera", "microphone", "geolocation", "payment"):
        assert f"{feature}=()" in pp, f"{feature} not disabled in {pp!r}"


def test_csp_present_on_normal_paths(client):
    r = client.get("/api/v1/ping")
    csp = r.headers.get("content-security-policy", "")
    assert csp, "CSP missing"
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "report-uri /api/v1/csp-report" in csp


def test_csp_nonce_appears_in_script_src(client):
    # Use /api/v1/ping which gets CSP (root / is CSP-free)
    r = client.get("/api/v1/ping")
    csp = r.headers.get("content-security-policy", "")
    # nonce is in script-src with the form 'nonce-...'
    assert "script-src 'self'" in csp or "script-src " in csp
    assert "'nonce-" in csp and len(csp.split("'nonce-")[1].split("'")[0]) >= 18


def test_nonce_differs_between_requests(client):
    # Use /api/v1/ping which gets CSP (root / is CSP-free)
    a = client.get("/api/v1/ping")
    b = client.get("/api/v1/ping")
    na = a.headers["content-security-policy"].split("'nonce-")[1].split("'")[0]
    nb = b.headers["content-security-policy"].split("'nonce-")[1].split("'")[0]
    assert na != nb


def test_cross_origin_isolation_headers(client):
    r = client.get("/")
    assert r.headers.get("cross-origin-opener-policy") == "same-origin"
    assert r.headers.get("cross-origin-resource-policy") == "same-origin"
    assert r.headers.get("x-permitted-cross-domain-policies") == "none"


# ── CSP bypass for WS ─────────────────────────────────


def test_websocket_path_skips_csp_but_keeps_hsts(app_with_headers):
    client = TestClient(app_with_headers)
    r = client.get("/ws/test")
    # HSTS still applied
    assert r.headers.get("strict-transport-security") == HSTS_VALUE
    # CSP intentionally not applied to WS upgrade paths
    assert "content-security-policy" not in r.headers


# ── CSP report endpoint ────────────────────────────────


def test_csp_report_modern_envelope(client):
    payload = {
        "reports": [
            {
                "type": "csp-violation",
                "body": {
                    "blocked-uri": "inline",
                    "violated-directive": "script-src-elem",
                    "document-uri": "https://pitchforge.io/dashboard",
                },
                "age": 0,
            }
        ]
    }
    r = client.post("/api/v1/csp-report", json=payload)
    assert r.status_code == 204


def test_csp_report_legacy_envelope(client):
    payload = {
        "csp-report": {
            "blocked-uri": "https://evil.example/x.js",
            "violated-directive": "script-src 'self'",
            "document-uri": "https://pitchforge.io/",
        }
    }
    r = client.post("/api/v1/csp-report", json=payload)
    assert r.status_code == 204


def test_csp_report_empty_body(client):
    r = client.post("/api/v1/csp-report", json={})
    assert r.status_code == 204


# ── Disable switch ─────────────────────────────────────


def test_security_headers_disabled(monkeypatch):
    monkeypatch.setenv("SECURITY_HEADERS_ENABLED", "false")
    # Re-import to pick up env var
    import importlib
    import app.middleware.security_headers as mod
    importlib.reload(mod)

    app = FastAPI()
    app.add_middleware(mod.SecurityHeadersMiddleware)

    @app.get("/")
    async def root():
        return {"ok": True}

    r = TestClient(app).get("/")
    assert "content-security-policy" not in r.headers
    assert "strict-transport-security" not in r.headers

    # Restore default
    monkeypatch.setenv("SECURITY_HEADERS_ENABLED", "true")
    importlib.reload(mod)


# ── Nonce helper ───────────────────────────────────────


def test_get_csp_nonce_returns_attribute(client):
    # Indirectly verified via CSP header, but also test the helper
    from starlette.requests import Request as StarletteRequest
    from starlette.datastructures import State

    # The helper expects request.state.csp_nonce to be set by the middleware
    state = State()
    state.csp_nonce = "abc123"
    scope = {"type": "http", "state": state}
    req = StarletteRequest(scope)
    assert get_csp_nonce(req) == "abc123"
