"""System routes — health check aggregation for status page monitoring."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/api/v1/system/health")
async def system_health():
    """Aggregated health check for all PitchForge services.
    
    Returns the status of each service component so an external
    monitoring tool (e.g. Instatus) can track uptime per service.
    """
    now = datetime.now(timezone.utc)

    # ── 1. API (always operational if this endpoint responds) ─
    # ── 2. Database (MongoDB) ──────────────────────────
    db_status = "operational"
    db_detail = ""
    try:
        from ..database import client
        if client is not None:
            try:
                await client.admin.command("ping")
                db_status = "operational"
            except Exception:
                db_status = "degraded"
                db_detail = "MongoDB ping failed"
        else:
            db_status = "degraded"
            db_detail = "MONGODB_URL not configured"
    except Exception as e:
        db_status = "down"
        db_detail = str(e)

    # ── 3. Research ────────────────────────────────────
    research_enabled = 0
    if settings.BRAVE_API_KEY:
        research_enabled += 1
    if settings.TAVILY_API_KEY:
        research_enabled += 1
    if settings.PERPLEXITY_API_KEY:
        research_enabled += 1
    research_status = (
        "operational" if research_enabled > 0 else "degraded"
    )
    research_detail = (
        f"{research_enabled} source(s) configured"
        if research_enabled > 0
        else "No research source configured"
    )

    # ── 4. Auth (Clerk) ────────────────────────────────
    auth_status = (
        "operational"
        if settings.CLERK_SECRET_KEY and settings.CLERK_PUBLISHABLE_KEY
        else "degraded"
    )
    auth_detail = (
        "Clerk configured" if auth_status == "operational"
        else "CLERK_SECRET_KEY / CLERK_PUBLISHABLE_KEY not set"
    )

    # ── 5. Billing (Stripe) ────────────────────────────
    billing_status = (
        "operational"
        if settings.STRIPE_API_KEY
        else "degraded"
    )
    billing_detail = (
        "Stripe configured" if billing_status == "operational"
        else "STRIPE_API_KEY not set"
    )

    # ── Aggregate ──────────────────────────────────────
    all_services = {
        "api": {"status": "operational"},
        "database": {"status": db_status, "detail": db_detail},
        "research": {"status": research_status, "detail": research_detail},
        "auth": {"status": auth_status, "detail": auth_detail},
        "billing": {"status": billing_status, "detail": billing_detail},
    }

    overall = "operational"
    for name, s in all_services.items():
        if s["status"] == "down":
            overall = "down"
            break
        if s["status"] == "degraded" and overall != "down":
            overall = "degraded"

    return {
        "status": overall,
        "app": settings.APP_NAME,
        "version": "0.3.0",
        "timestamp": now.isoformat(),
        "services": all_services,
        "uptime_url": "/health",   # legacy health check
    }


@router.get("/api/v1/system/ready")
async def system_readiness():
    """Readiness probe — returns 200 when the server can accept traffic."""
    return {"status": "ready", "timestamp": datetime.now(timezone.utc).isoformat()}
