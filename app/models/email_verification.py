"""Email verification model — TASK-022.

Token-based email verification flow:
  1. User signs up (or we send a verification email manually).
  2. We generate a 32-byte random token, store only its hash in DB,
     and email the plaintext link to the user.
  3. User clicks; the route validates the hash, marks the user
     `email_verified=True`, and (optionally) consumes the token.
  4. Tokens expire after 24h; resend is rate-limited to 3 per day per user.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


class EmailVerification(Document):
    """A pending email verification for a user.

    One ACTIVE row per user (status='pending'); previous ones are marked
    'superseded' when a new one is issued (so a user can only have one
    "live" link at a time).
    """

    user_id: Indexed(str)
    email: str  # the email being verified (may differ from user's primary if they change it)
    token_hash: str  # SHA-256 of the plaintext token we sent
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=24)
    )
    used_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None
    status: str = "pending"  # pending / used / expired / superseded
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    send_count_today: int = 0  # how many sends in the last 24h
    last_sent_at: Optional[datetime] = None

    class Settings:
        name = "email_verifications"
        indexes = [
            "user_id",
            [("user_id", 1), ("status", 1)],
            [("user_id", 1), ("last_sent_at", -1)],
        ]
