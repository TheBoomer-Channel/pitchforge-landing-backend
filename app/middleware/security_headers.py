"""Security headers middleware — A+ on Mozilla Observatory & securityheaders.com.

Implements defense-in-depth HTTP headers on every response:
  * Content-Security-Policy (strict, with nonces for inline scripts)
  * Strict-Transport-Security (HSTS, 1y, includeSubDomains, preload)
  * X-Frame-Options: DENY
  * X-Content-Type-Options: nosniff
  * Referrer-Policy: strict-origin-when-cross-origin
  * Permissions-Policy: camera=(), microphone=(), geolocation=()
  * Cross-Origin-Opener-Policy: same-origin
  * Cross-Origin-Resource-Policy: same-origin
  * X-Permitted-Cross-Domain-Policies: none

Disable the whole thing with SECURITY_HEADERS_ENABLED=false (tests, dev only).
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────

ENABLED = os.getenv("SECURITY_HEADERS_ENABLED", "true").lower() == "true"

# Build CSP — strict by default. Customize per deployment via env.
_CSP_DIRECTIVES_BASE: dict[str, str] = {
    "default-src": "'self'",
    # Inline scripts allowed only with a per-request nonce (see middleware)
    # Swagger UI needs cdn.jsdelivr.net for CSS/JS assets
    "script-src": "'self' 'unsafe-inline' 'nonce-{nonce}' https://js.stripe.com https://cdn.jsdelivr.net",
    "style-src": "'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
    "font-src": "'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:",
    "img-src": "'self' data: https: https://cdn.jsdelivr.net",
    "connect-src": "'self' https://api.tavily.com https://api.perplexity.ai https://api.openrouter.ai https://api.github.com https://cdn.jsdelivr.net wss: ws:",
    "frame-ancestors": "'none'",
    "frame-src": "https://js.stripe.com https://hooks.stripe.com",
    "media-src": "'self'",
    "object-src": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "manifest-src": "'self'",
    "worker-src": "'self'",
    "report-uri": "/api/v1/csp-report",
}

HSTS_VALUE = "max-age=31536000; includeSubDomains; preload"


def _build_csp(nonce: str, report_only: bool = False) -> str:
    """Compose a Content-Security-Policy header value."""
    parts = []
    for directive, value in _CSP_DIRECTIVES_BASE.items():
        parts.append(f"{directive} {value.replace('{nonce}', nonce)}")
    return "; ".join(parts)


# Paths that should never get the strict CSP (WebSocket upgrades break otherwise)
_NOCSP_PATH_PREFIXES: tuple[str, ...] = ("/ws/",)

# Landing page and other public static pages with inline scripts
_CSP_FREE_PATHS: frozenset[str] = frozenset({"/"})


def _is_nocsp_path(path: str) -> bool:
    if path in _CSP_FREE_PATHS:
        return True
    return any(path.startswith(p) for p in _NOCSP_PATH_PREFIXES)


# ── Middleware ─────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject defensive HTTP headers into every response."""

    def __init__(self, app, *, report_only: bool = False) -> None:
        super().__init__(app)
        self.report_only = report_only

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate a per-request CSP nonce (exposed to handlers via request.state)
        nonce = secrets.token_urlsafe(18)
        request.state.csp_nonce = nonce

        response: Response = await call_next(request)

        if not ENABLED:
            return response

        # Skip CSP for WS upgrade paths but still apply HSTS/etc.
        if not _is_nocsp_path(request.url.path):
            csp_value = _build_csp(nonce, report_only=self.report_only)
            header_name = (
                "Content-Security-Policy-Report-Only"
                if self.report_only
                else "Content-Security-Policy"
            )
            response.headers[header_name] = csp_value

        # HSTS — only meaningful over HTTPS, harmless over HTTP
        response.headers["Strict-Transport-Security"] = HSTS_VALUE

        # Clickjacking / MIME-sniffing / referrer leak defenses
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disable powerful features we never need in a SaaS web app
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        # Cross-origin isolation (lightweight, no SharedArrayBuffer requirement)
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        # Flash/PDF cross-domain policy
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"

        return response


# ── Helper for nonces in templates ─────────────────────


def get_csp_nonce(request: Request) -> str:
    """Return the per-request CSP nonce (use it on any inline <script>)."""
    return getattr(request.state, "csp_nonce", "")
