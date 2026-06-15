"""Webhook Beanie models — WebhookEndpoint + WebhookDelivery (TASK-043)."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


# ── Supported webhook event types ──────────────────────

WEBHOOK_EVENTS = [
    "project.created",
    "research.completed",
    "research.failed",
    "pitch.generated",
    "landing.generated",
    "ping",  # Test event
]


class WebhookEndpoint(Document):
    """A user-registered webhook endpoint that receives event notifications.

    Each endpoint is tied to a user, has a shared secret for HMAC-SHA256
    signing, and subscribes to one or more event types.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Indexed(str)
    url: str
    description: str = ""
    events: list[str] = Field(default_factory=list)  # e.g. ["project.created", "research.completed"]
    secret: str  # Shared secret for HMAC-SHA256 (generated on creation)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_triggered_at: Optional[datetime] = None
    delivery_count: int = 0
    failure_count: int = 0

    class Settings:
        name = "webhook_endpoints"
        indexes = [
            "user_id",
            [("user_id", 1), ("is_active", 1)],
        ]


class WebhookDelivery(Document):
    """Log of every webhook delivery attempt (for debugging/retry).

    One row per dispatch attempt. Successful deliveries have status='success'.
    Failed deliveries have status='failed' with error detail.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    endpoint_id: Indexed(str)
    event_type: str
    payload: dict = Field(default_factory=dict)
    status: str = "pending"  # pending / success / failed
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    attempt: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: Optional[int] = None

    class Settings:
        name = "webhook_deliveries"
        indexes = [
            "endpoint_id",
            [("endpoint_id", 1), ("created_at", -1)],
            [("status", 1)],
        ]
