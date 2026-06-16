"""FastAPI main app — entry point with all routes, auth, WS, and middleware.

Enhanced with auth, Stripe checkout, WebSocket, rate limiting, structured logging,
and dashboard serving — merged from Startup Engine, June 2026.
"""

import logging
import os
import uuid
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

try:
    from sentry_sdk.integrations.mongo import MongoIntegration
except ImportError:
    MongoIntegration = None  # removed in newer sentry-sdk versions


from .config import settings
from .database import init_db, close_db
from .telemetry import init_telemetry, shutdown_telemetry
from .routes import research, dashboard, planning, generate, projects, github, skills, tokens, limits
from .routes import auth as auth_routes
from .routes import checkout as checkout_routes
from .routes import settings_api
from .routes import pdf as pdf_routes
from .routes import versions as versions_routes
from .routes import csp_report as csp_report_routes
from .routes import legal as legal_routes
from .routes import gdpr as gdpr_routes
from .routes import email_verification as email_verification_routes
from .routes import two_factor as two_factor_routes
from .routes import audit as audit_routes
from .routes import trial as trial_routes
from .routes import usage as usage_routes
from .routes import coupons as coupons_routes
from .routes import system as system_routes
from .routes import llm_costs as llm_costs_routes
from .routes import llm_router as llm_router_routes
from .email_lifecycle.routes import router as email_lifecycle_router
from .referrals.routes import router as referral_router
from .webhooks.routes import router as webhook_router
from .routes import marketplace as marketplace_routes
from .routes import ab_copy as ab_copy_routes
from .routes import ab_prompts as ab_prompts_routes
from .routes import waitlist as waitlist_routes
from .routes import landing_generate as landing_generate_routes
from .routes import landing_capture as landing_capture_routes
from .middleware.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL, logging.INFO))

# ── Dashboard path (computed once at module load) ─────

_dashboard_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir, "frontend", "dashboard"
)
_dashboard_dir = os.path.normpath(_dashboard_dir)


# ── Lifespan ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    logger.info(f"Starting {settings.APP_NAME} v0.4.0...")

    # Init OpenTelemetry (non-blocking — safe to fail)
    init_telemetry()

    await init_db()
    logger.info("MongoDB initialized via Beanie")

    # Start Redis WS bridge if redis is configured
    try:
        from .ws import manager as ws_manager
        app.state.ws_manager = ws_manager
        logger.info("WebSocket manager initialized")
    except Exception as e:
        logger.warning(f"WebSocket not available: {e}")

    yield

    await close_db()
    shutdown_telemetry()
    logger.info("Shutting down...")


# ── OpenAPI tags ───────────────────────────────────────

TAGS_METADATA = [
    {"name": "auth", "description": "Clerk-authenticated user profile & sync. Register/login via Clerk frontend SDK."},
    {"name": "research", "description": "Multi-source startup idea research (web, HN, Reddit, GitHub, etc.)"},
    {"name": "planning", "description": "Full planning pipeline: PRD → Functional → Financial → Technical specs"},
    {"name": "generate", "description": "Generate pitch decks, landing pages, and pricing pages"},
    {"name": "checkout", "description": "Stripe checkout integration for paid tiers"},
    {"name": "github", "description": "GitHub integration — connect repos, commit, push"},
    {"name": "settings", "description": "User settings: API keys management"},
    {"name": "limits", "description": "Tier usage limits and counters"},
    {"name": "tokens", "description": "Token balance and code generation billing"},
    {"name": "dashboard", "description": "Simple HTML dashboard"},
    {"name": "pdf", "description": "PDF export for pitch decks and reports"},
    {"name": "versions", "description": "Project version history — snapshot and restore project state"},
    {"name": "legal", "description": "ToS, Privacy, Cookie Policy, Acceptable Use — versioned, with acceptance tracking"},
    {"name": "gdpr", "description": "Data subject rights: export, deletion, consents"},
    {"name": "auth", "description": "Authentication (Clerk) + email verification magic links + 2FA / TOTP (RFC 6238)"},
    {"name": "admin", "description": "Admin endpoints: audit log access, chain verification"},
    {"name": "webhooks", "description": "Webhook endpoints — register and manage outgoing webhooks with HMAC-SHA256 signing"},
    {"name": "coupons", "description": "Coupon codes & discounts — validate, apply to checkout, admin CRUD"},
    {"name": "llm", "description": "LLM Router — multi-model routing status, circuit breaker metrics, and fallback chain monitoring (TASK-056)"},
    {"name": "marketplace", "description": "Template Marketplace — publish, browse, purchase templates with Stripe Connect 70/30 split (TASK-053)"},
]

def _custom_openapi():
    """Inject ClerkSession and ApiKey security schemes into OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "ClerkSession": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Clerk session token. Get it from your browser's Application > Cookies > __session or call Clerk's getToken().",
        },
        "ApiKey": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Your personal API key from Settings > API Keys (starts with 'sf_').",
        },
    }
    schema["security"] = [
        {"ClerkSession": []},
        {"ApiKey": []},
    ]
    app.openapi_schema = schema
    return schema


# ── App ────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version="0.3.0",
    description="AI-powered pitch deck & startup validation platform\n\n"
    "## Authentication\n"
    "This API uses [Clerk](https://clerk.com) for authentication.\n\n"
    "1. **Frontend users**: Sign up/login via the web app. Sessions are managed automatically by Clerk.\n"
    "2. **API access**: Get your personal API key from **Settings → API Keys** in the dashboard. "
    "Pass it via the `X-API-Key` header or as `sf_...` Bearer token.\n"
    "3. **API Reference**: Visit `/docs` to explore and test endpoints with the Scalar API Reference.\n"
    "\n"
    "[Clerk Dashboard](https://blessed-octopus-60.clerk.accounts.dev) | "
    "[Stripe Dashboard](https://dashboard.stripe.com)",
    docs_url=None,  # We serve Scalar instead at /docs
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
)

# Inject custom OpenAPI schema with ClerkSession + ApiKey security schemes
app.openapi = _custom_openapi


# ── CORS ───────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Security headers (CSP, HSTS, etc.) — TASK-013 ──────

app.add_middleware(SecurityHeadersMiddleware)
logger.info("Security headers middleware enabled (CSP, HSTS, Permissions-Policy)")


# ── Sentry (error tracking) — TASK-023 ─────────────────

try:
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            release=settings.SENTRY_RELEASE,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
                *([MongoIntegration()] if MongoIntegration else []),
            ],
            traces_sample_rate=0.1,
            # Send request body (stripped of sensitive data)
            send_default_pii=False,
            max_request_body_size="medium",
        )
        logger.info(f"Sentry initialized — environment={settings.SENTRY_ENVIRONMENT}")
    else:
        logger.info("SENTRY_DSN not set — Sentry disabled")
except Exception as e:
    logger.warning(f"Sentry init failed (non-fatal): {e}")

# ── Rate limiting (slowapi) ────────────────────────────

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    def _rate_limit_key(request: Request) -> str:
        """Rate limit key: prefer API key identity, fall back to IP.

        TASK-043 — Per-key rate limiting:
        - Free tier: 1000 req/h
        - Pro tier: 10K req/h
        - If no API key, use client IP (default).
        """
        # Check for API key in headers
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer sf_"):
                api_key = auth[7:]
        if api_key and api_key.startswith("sf_"):
            return f"key:{api_key[:16]}"
        return get_remote_address(request)

    limiter = Limiter(
        key_func=_rate_limit_key,
        default_limits=[settings.RATE_LIMIT_GENERAL],
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    logger.info("Rate limiting enabled")
except ImportError:
    logger.warning("slowapi not installed — rate limiting disabled")
    limiter = None


# ── Structured request logging ─────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request with a unique ID and timing."""
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start = time.monotonic()

    response = await call_next(request)

    elapsed_ms = round((time.monotonic() - start) * 1000)
    logger.info(
        f"[{request_id}] {request.method} {request.url.path} "
        f"→ {response.status_code} ({elapsed_ms}ms)"
    )
    response.headers["X-Request-ID"] = request_id
    return response


# ── Auth middleware ────────────────────────────────────

PUBLIC_PATH_PREFIXES = {
    "/", "/health", "/docs", "/openapi.json", "/redoc",
    "/api/webhook",  # Stripe webhook
    "/api/v1/email/webhook",  # Resend webhook
    "/api/v1/email/unsubscribe",  # One-click unsubscribe (public)
    "/api/v1/webhook",  # Public webhook endpoint (if any)
    "/dashboard",  # Static files
    "/api/download",  # Asset download (public for preview)
    "/api/files",     # Asset file listing (public for preview)
    "/api/v1/marketplace/templates",    # Marketplace public browse + detail/preview (no trailing slash — prefix matching uses startswith)
    "/api/v1/marketplace/landing-data",  # Public landing preview data
    "/api/v1/ab-prompts/assign",  # Public variant assignment (runtime)
    "/api/v1/ab-prompts/log",  # Public execution logging (runtime)
    "/api/v1/ab-prompts/rate",  # Public output rating (runtime)
    "/api/v1/ab-prompts/score",  # Public quality scoring (runtime)
    "/api/waitlist",  # Waitlist subscription (public)
    "/api/contact/submit",  # Contact form from landing pages (public)
    "/api/survey/submit",  # Survey form from landing pages (public)
    "/api/v1/landing",  # Landing page generation (public product endpoint - no trailing slash!)
}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Authenticate via Clerk JWT or per-user API key, with public path bypass."""
    path = request.url.path.rstrip("/") or "/"

    # Allow public paths
    is_public = any(
        path == p or path.startswith(p + "/") or path.startswith(p + "?")
        for p in PUBLIC_PATH_PREFIXES
    )
    if is_public:
        return await call_next(request)

    # Try per-user API key from X-API-Key header
    api_key = request.headers.get("X-API-Key", "")
    auth_header = request.headers.get("Authorization", "")

    if not api_key and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token.startswith("sf_"):
            api_key = token

    if api_key:
        try:
            from .database import ApiKey
            from .routes.settings_api import verify_api_key

            prefix = api_key[:12]
            keys = await ApiKey.find(
                ApiKey.key_prefix == prefix,
                ApiKey.is_active == True,
            ).to_list()

            for k in keys:
                if verify_api_key(api_key, k.key_hash):
                    k.last_used_at = datetime.now(timezone.utc)
                    await k.save()
                    request.state.api_key_user_id = k.user_id
                    return await call_next(request)
        except Exception as e:
            logger.warning(f"API key lookup failed: {e}")

        if settings.API_KEY and api_key == settings.API_KEY:
            return await call_next(request)

    if not settings.API_KEY and not settings.CLERK_SECRET_KEY:
        return await call_next(request)

    if auth_header.startswith("Bearer ") and auth_header[7:] == settings.API_KEY:
        return await call_next(request)

    return await call_next(request)


# ── Scalar API Reference (replaces Swagger UI) ──────────

_SCALAR_HTML = """<!DOCTYPE html>
<html>
  <head>
    <title>PitchForge — API Reference</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body { margin: 0; }
    </style>
  </head>
  <body>
    <script
      id="api-reference"
      data-url="/openapi.json"
      data-theme="default"
      data-layout="modern"
      data-show-test-request-button="true"
      data-custom-css="
        :root {
          --scalar-color-accent: #0ea5e9;
          --scalar-background-1: #0a1628;
          --scalar-background-2: #0f2240;
          --scalar-background-3: #162d50;
          --scalar-color-1: #f1f5f9;
          --scalar-color-2: #94a3b8;
          --scalar-color-3: #64748b;
          --scalar-color-border: rgba(14, 165, 233, 0.2);
        }
        .scalar-api-reference .section-flare { display: none; }
      "">
    </script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>
"""


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    """Scalar API Reference — modern, interactive API documentation."""
    return HTMLResponse(_SCALAR_HTML)


# ── Routes ─────────────────────────────────────────────

app.include_router(auth_routes.router)
app.include_router(checkout_routes.router)
app.include_router(research.router)
app.include_router(dashboard.router)
app.include_router(planning.router)
app.include_router(generate.router)
app.include_router(projects.router)
app.include_router(settings_api.router)
app.include_router(github.router)
app.include_router(skills.router)
app.include_router(tokens.router)
app.include_router(limits.router)
app.include_router(pdf_routes.router)
app.include_router(versions_routes.router)
app.include_router(csp_report_routes.router)
app.include_router(legal_routes.router)
app.include_router(gdpr_routes.router)
app.include_router(email_verification_routes.router)
app.include_router(two_factor_routes.router)
app.include_router(audit_routes.router)
app.include_router(trial_routes.router)
app.include_router(usage_routes.router)
app.include_router(coupons_routes.router)
app.include_router(system_routes.router)
app.include_router(llm_costs_routes.router)
app.include_router(llm_router_routes.router)
app.include_router(email_lifecycle_router)
app.include_router(referral_router)
app.include_router(webhook_router)
app.include_router(marketplace_routes.router)
app.include_router(ab_copy_routes.router)
app.include_router(ab_prompts_routes.router)
app.include_router(waitlist_routes.router)
app.include_router(landing_capture_routes.router)
app.include_router(landing_generate_routes.router)


# ── WebSocket ──────────────────────────────────────────

try:
    from .ws import manager as ws_manager

    @app.websocket("/ws/{job_id}")
    async def websocket_job(websocket, job_id: str):
        await ws_manager.connect(job_id, websocket)
        try:
            while True:
                # Keep connection alive; client can send pings
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except Exception:
            pass
        finally:
            await ws_manager.disconnect(job_id, websocket)

    logger.info("WebSocket endpoint registered at /ws/{job_id}")
except ImportError:
    logger.warning("WebSocket dependencies not available")


# ── Dashboard static files ─────────────────────────────

if os.path.isdir(_dashboard_dir):
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")
    logger.info(f"Dashboard served from {_dashboard_dir}")
else:
    logger.info("No dashboard frontend directory found")

# ── Landing page (route handler, not static mount) ──────

_LANDING_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, os.pardir, "landing"
)
_LANDING_DIR = os.path.normpath(_LANDING_DIR)
# Fallback: try parent project root if code/landing not found
if not os.path.isdir(_LANDING_DIR):
    _LANDING_DIR = "/home/admin/code/startup-factory/code/landing"
_LANDING_HTML = os.path.join(_LANDING_DIR, "index.html")


@app.get("/", include_in_schema=False)
async def landing_page():
    """Serve the landing page. Falls back to dashboard redirect or API index."""
    if os.path.exists(_LANDING_HTML):
        with open(_LANDING_HTML) as f:
            return HTMLResponse(f.read())
    # Fallback: dashboard or API index
    if os.path.isdir(_LANDING_DIR if False else _dashboard_dir):
        return RedirectResponse(url="/dashboard")
    return {
        "app": settings.APP_NAME,
        "version": "0.3.0",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "health": "/health",
    }


# ── Health ─────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint — returns app status and component health."""
    # Check MongoDB connectivity
    db_status = "disconnected"
    db_detail = ""
    try:
        from .database import client
        if client is not None:
            try:
                await client.admin.command('ping')
                db_status = "connected"
            except Exception:
                db_status = "disconnected"
        else:
            db_status = "not_configured"
            db_detail = "MONGODB_URL not set"
    except Exception:
        db_status = "error"

    return {
        "status": "ok" if db_status in ("connected", "not_configured") else "degraded",
        "app": settings.APP_NAME,
        "version": "0.3.0",
        "components": {
            "database": {"status": db_status, "detail": db_detail},
            "websocket": {"status": "enabled" if hasattr(app.state, 'ws_manager') else "disabled"},
            "gemini_image_gen": {"status": "configured" if settings.GEMINI_API_KEY else "not_configured"},
        },
    }



