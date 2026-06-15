"""Email lifecycle models — TASK-040.

Two new Beanie documents:
  * EmailEvent — records every email sent (for open/click tracking + audit)
  * UnsubscribeToken — GDPR-compliant one-click unsubscribe tokens
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from beanie import Document, Indexed
from pydantic import Field


class EmailEvent(Document):
    """Records every transactional email sent, plus open/click webhook events.

    One row per email. Open/click events from Resend webhooks update this row.
    """

    event_id: Indexed(str, unique=True) = Field(
        default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}"
    )
    user_id: str  # Clerk user ID
    to_email: str
    email_type: str  # welcome / first_project / activation / upgrade_prompt / winback / verification / trial_milestone / trial_expired
    subject: str
    resend_id: str | None = None  # Resend message ID (set after send)
    status: str = "pending"  # pending / sent / failed / opened / clicked
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "email_events"
        indexes = [
            "user_id",
            "resend_id",
            "event_id",
            [("user_id", 1), ("created_at", -1)],
            [("email_type", 1), ("created_at", -1)],
        ]


class UnsubscribeToken(Document):
    """One-click unsubscribe token (GDPR / CAN-SPAM compliant).

    Each token is unique per user. Clicking the unsubscribe link sets
    the user's email_opt_out flag and marks the token as consumed.
    """

    token_id: Indexed(str, unique=True) = Field(
        default_factory=lambda: f"unsub_{uuid.uuid4().hex[:16]}"
    )
    user_id: str
    token_hash: str  # SHA-256 of the token
    status: str = "active"  # active / consumed / expired
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    consumed_at: datetime | None = None
    # Tokens expire after 90 days (GDPR: unsubscribe must work for "a reasonable period")
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=90)
    )

    class Settings:
        name = "unsubscribe_tokens"
        indexes = [
            "token_hash",
            "user_id",
            [("user_id", 1), ("status", 1)],
        ]
