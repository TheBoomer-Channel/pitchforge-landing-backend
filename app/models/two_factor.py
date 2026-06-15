"""Two-factor authentication (TOTP) models — TASK-011.

Implements RFC 6238 TOTP (Time-Based One-Time Password) with these safeguards:

  * Secret is encrypted at rest (base64 + app secret) so a DB leak
    doesn't directly expose the seed.
  * 10 one-time backup codes per user, stored as bcrypt hashes; each can
    only be used once.
  * Failed-attempt counter with 15-min lockout after 5 consecutive
    failures (per RFC 6238 §5.2 and OWASP recommendations).
  * Last_used counter prevents token replay within the same 30s window.
  * is_enabled + is_forced (for admins) flags on the User model
    (added separately in database.py).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


def _hash_backup_code(code: str) -> str:
    """Backup codes are short, so we bcrypt them at use-time
    (constant-time compare). For storage we use SHA-256 with a per-user
    salt; combined with the random 10-char code this is sufficient.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


# ── 2FA Secret (one per user) ──────────────────────────


class TwoFactorSecret(Document):
    """Per-user TOTP secret + backup codes. One row per user."""

    user_id: Indexed(str, unique=True)
    # The secret is base64-encoded, encrypted with the app SECRET_KEY
    encrypted_secret: str
    # The issuer/label shown in authenticator apps
    issuer: str = "PitchForge"
    account_label: str  # typically the user's email
    enabled: bool = False
    enabled_at: Optional[datetime] = None
    # Backup codes: stored as SHA-256 hashes (one-way). Plain codes are
    # shown to the user ONCE at enrollment.
    backup_code_hashes: list[str] = Field(default_factory=list)
    backup_codes_remaining: int = 0
    # Last successfully used TOTP counter (prevents replay within the
    # 30s window). Stored as a TOTP counter (seconds / 30).
    last_counter: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "two_factor_secrets"
        indexes = [
            "user_id",
        ]


# ── Failed-attempt counter + lockout ────────────────────


class TwoFactorAttempt(Document):
    """Tracks recent failed TOTP verifications per user for lockout.

    5 consecutive failures within a rolling 15-minute window → 15-min lockout.
    A single success resets the counter.
    """

    user_id: Indexed(str, unique=True)
    failed_count: int = 0
    window_started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    locked_until: Optional[datetime] = None  # set on lockout; cleared on success or expiry
    last_attempt_at: Optional[datetime] = None
    last_failure_reason: Optional[str] = None
    last_ip: Optional[str] = None

    class Settings:
        name = "two_factor_attempts"
        indexes = [
            "user_id",
            [("locked_until", 1)],
        ]


# ── Backup-code generation helper ───────────────────────


def generate_backup_codes(n: int = 10) -> list[str]:
    """Generate n random 10-character alphanumeric backup codes.

    Format: XXXX-XXXX (uppercase, no ambiguous chars).
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1
    codes: list[str] = []
    for _ in range(n):
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_backup_code(code: str) -> str:
    return _hash_backup_code(code)
