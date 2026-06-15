"""Webhook management routes — CRUD + test trigger (TASK-043)."""

import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..database import User
from .models import WebhookEndpoint, WebhookDelivery, WEBHOOK_EVENTS
from .dispatcher import dispatch_webhooks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


# ── Request body models ────────────────────────────────

class CreateWebhookRequest(BaseModel):
    url: str = Field(..., description="The HTTPS URL that will receive POST requests", min_length=8)
    events: list[str] = Field(..., description="Event types to subscribe to", min_length=1)
    description: str = Field("", description="Optional human-readable label")


# ── Helpers ────────────────────────────────────────────

def _generate_secret() -> str:
    """Generate a cryptographically random webhook secret (64 hex chars)."""
    return secrets.token_hex(32)


# ── List endpoints ─────────────────────────────────────

@router.get("/endpoints")
async def list_endpoints(user: User = Depends(get_current_user)):
    """List all webhook endpoints for the authenticated user."""
    endpoints = await WebhookEndpoint.find(
        WebhookEndpoint.user_id == user.clerk_user_id
    ).sort(-WebhookEndpoint.created_at).to_list()

    return {
        "endpoints": [
            {
                "id": ep.id,
                "url": ep.url,
                "description": ep.description,
                "events": ep.events,
                "is_active": ep.is_active,
                "created_at": ep.created_at.isoformat() if ep.created_at else None,
                "last_triggered_at": ep.last_triggered_at.isoformat() if ep.last_triggered_at else None,
                "delivery_count": ep.delivery_count,
                "failure_count": ep.failure_count,
            }
            for ep in endpoints
        ],
        "total": len(endpoints),
        "available_events": WEBHOOK_EVENTS,
    }


# ── Create endpoint ────────────────────────────────────

@router.post("/endpoints", status_code=201)
async def create_endpoint(
    body: CreateWebhookRequest = Body(...),
    user: User = Depends(get_current_user),
):
    """Register a new webhook endpoint.

    Request body:
    - `url`: The HTTPS URL that will receive POST requests.
    - `events`: List of event types (e.g., `["project.created", "research.completed"]`).
    - `description`: Optional human-readable label.

    A cryptographically random secret is generated and returned ONCE.
    Store it securely — it won't be shown again.
    """
    # Validate URL
    if not body.url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Webhook URL must use HTTPS")

    # Validate events
    invalid = [e for e in body.events if e not in WEBHOOK_EVENTS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event types: {', '.join(invalid)}. "
            f"Available: {', '.join(WEBHOOK_EVENTS)}",
        )

    secret = _generate_secret()
    endpoint = WebhookEndpoint(
        id=str(uuid.uuid4()),
        user_id=user.clerk_user_id,
        url=body.url,
        description=body.description,
        events=body.events,
        secret=secret,
    )
    await endpoint.insert()

    return {
        "id": endpoint.id,
        "url": endpoint.url,
        "description": endpoint.description,
        "events": endpoint.events,
        "secret": secret,
        "message": "Store this secret securely — it will not be shown again.",
    }


# ── Delete endpoint ────────────────────────────────────

@router.delete("/endpoints/{endpoint_id}")
async def delete_endpoint(endpoint_id: str, user: User = Depends(get_current_user)):
    """Permanently delete a webhook endpoint."""
    endpoint = await WebhookEndpoint.find_one(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.user_id == user.clerk_user_id,
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    await endpoint.delete()
    return {"status": "deleted", "id": endpoint_id}


# ── Toggle active status ───────────────────────────────

@router.post("/endpoints/{endpoint_id}/toggle")
async def toggle_endpoint(
    endpoint_id: str,
    active: bool = Query(..., description="Set to true to enable, false to disable"),
    user: User = Depends(get_current_user),
):
    """Enable or disable a webhook endpoint without deleting it."""
    endpoint = await WebhookEndpoint.find_one(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.user_id == user.clerk_user_id,
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    endpoint.is_active = active
    await endpoint.save()

    return {"id": endpoint_id, "is_active": endpoint.is_active}


# ── Delivery history ───────────────────────────────────

@router.get("/endpoints/{endpoint_id}/deliveries")
async def list_deliveries(
    endpoint_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    """List recent delivery attempts for a webhook endpoint."""
    # Verify ownership
    endpoint = await WebhookEndpoint.find_one(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.user_id == user.clerk_user_id,
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    deliveries = await WebhookDelivery.find(
        WebhookDelivery.endpoint_id == endpoint_id,
    ).sort(-WebhookDelivery.created_at).limit(limit).to_list()

    return {
        "deliveries": [
            {
                "id": d.id,
                "event_type": d.event_type,
                "status": d.status,
                "response_status": d.response_status,
                "error": d.error,
                "attempt": d.attempt,
                "duration_ms": d.duration_ms,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in deliveries
        ],
        "total": len(deliveries),
    }


# ── Test trigger ───────────────────────────────────────

@router.post("/endpoints/{endpoint_id}/test")
async def test_endpoint(
    endpoint_id: str,
    user: User = Depends(get_current_user),
):
    """Send a test ping to the webhook endpoint.

    Dispatches a `ping` event with dummy payload.
    Use this to verify your endpoint is receiving webhooks correctly.
    """
    endpoint = await WebhookEndpoint.find_one(
        WebhookEndpoint.id == endpoint_id,
        WebhookEndpoint.user_id == user.clerk_user_id,
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    count = await dispatch_webhooks("ping", {
        "event": "ping",
        "message": "This is a test webhook from PitchForge.",
        "endpoint_id": endpoint_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "status": "dispatched" if count > 0 else "no_active_endpoints",
        "endpoint_id": endpoint_id,
    }
