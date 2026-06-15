"""Audit event model — TASK-014.

Immutable, append-only audit log of security- and billing-sensitive actions.

Tamper-evidence:
  Each row has `prev_hash` (the `this_hash` of the previous row for the
  same scope) and `this_hash` = SHA-256(prev_hash || canonical_json(row)).
  Verifying the chain is O(N) and lets us detect any insertion, deletion,
  or modification after the fact.

Indexes:
  - (user_id, created_at desc) — per-user history
  - (action, created_at desc) — action-wide history
  - (created_at desc) — global feed
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field

# Genesis hash — the prev_hash of the very first audit row
GENESIS_HASH = "0" * 64


def _canonical_json(obj: dict) -> str:
    """Deterministic JSON serialization (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_chain_hash(prev_hash: str, row: dict) -> str:
    """Compute this_hash = SHA-256(prev_hash || canonical_json(row)).

    `row` must NOT include `prev_hash` or `this_hash` themselves.
    """
    payload = prev_hash + _canonical_json(row)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditEvent(Document):
    """A single audit event. Once written, it must never be updated."""

    # Monotonic sequence within the global scope (for fast pagination)
    seq: Indexed(int)

    # Who (nullable for system/anonymous events like failed logins)
    user_id: Optional[str] = None
    user_email: Optional[str] = None

    # What
    action: Indexed(str)  # e.g., "auth.login.success", "billing.subscription.created"
    target_type: Optional[str] = None  # e.g., "project", "api_key"
    target_id: Optional[str] = None

    # Where
    ip: Optional[str] = None
    user_agent: Optional[str] = None

    # When
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Free-form structured context (kept small, < 4KB)
    metadata: dict = Field(default_factory=dict)

    # Chain
    prev_hash: str = GENESIS_HASH
    this_hash: str

    class Settings:
        name = "audit_events"
        indexes = [
            "seq",
            "action",
            "user_id",
            [("user_id", 1), ("created_at", -1)],
            [("action", 1), ("created_at", -1)],
            [("created_at", -1)],
        ]


# ── Action constants (use these to avoid typos) ─────────


class AuditAction:
    # Authentication
    AUTH_LOGIN_SUCCESS = "auth.login.success"
    AUTH_LOGIN_FAILED = "auth.login.failed"
    AUTH_LOGOUT = "auth.logout"
    AUTH_2FA_ENABLED = "auth.2fa.enabled"
    AUTH_2FA_DISABLED = "auth.2fa.disabled"
    AUTH_2FA_VERIFY_FAILED = "auth.2fa.verify.failed"
    AUTH_2FA_LOCKOUT = "auth.2fa.lockout"
    AUTH_PASSWORD_RESET = "auth.password.reset"
    AUTH_EMAIL_VERIFICATION_SENT = "auth.email.verification.sent"
    AUTH_EMAIL_VERIFIED = "auth.email.verified"

    # Account
    ACCOUNT_CREATED = "account.created"
    ACCOUNT_DELETION_REQUESTED = "account.deletion.requested"
    ACCOUNT_DELETION_CANCELLED = "account.deletion.cancelled"
    ACCOUNT_DELETION_COMPLETED = "account.deletion.completed"

    # Legal & GDPR
    LEGAL_ACCEPTED = "legal.accepted"
    GDPR_EXPORT = "gdpr.export"
    GDPR_CONSENT_GRANTED = "gdpr.consent.granted"
    GDPR_CONSENT_WITHDRAWN = "gdpr.consent.withdrawn"

    # Billing (TASK-016)
    BILLING_SUBSCRIPTION_CREATED = "billing.subscription.created"
    BILLING_SUBSCRIPTION_UPDATED = "billing.subscription.updated"
    BILLING_SUBSCRIPTION_CANCELLED = "billing.subscription.cancelled"
    BILLING_PAYMENT_SUCCESS = "billing.payment.success"
    BILLING_PAYMENT_FAILED = "billing.payment.failed"
    BILLING_COUPON_REDEEMED = "billing.coupon.redeemed"
    BILLING_COUPON_CREATED = "billing.coupon.created"
    BILLING_COUPON_UPDATED = "billing.coupon.updated"
    BILLING_COUPON_DELETED = "billing.coupon.deleted"

    # API keys
    APIKEY_CREATED = "apikey.created"
    APIKEY_REVOKED = "apikey.revoked"

    # Settings / admin
    SETTINGS_TIER_CHANGED = "settings.tier.changed"
    SETTINGS_PROFILE_UPDATED = "settings.profile.updated"
    SETTINGS_THEME_CHANGED = "settings.theme.changed"
    SETTINGS_LANG_CHANGED = "settings.lang.changed"
    ADMIN_ACTION = "admin.action"

    # Project
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"

    # Research
    RESEARCH_STARTED = "research.started"
    RESEARCH_COMPLETED = "research.completed"
    RESEARCH_FAILED = "research.failed"

    # Planning
    PLANNING_STARTED = "planning.started"
    PLANNING_COMPLETED = "planning.completed"

    # Code generation
    CODEGEN_STARTED = "codegen.started"
    CODEGEN_COMPLETED = "codegen.completed"
    CODEGEN_FAILED = "codegen.failed"

    # Asset generation
    PITCH_GENERATED = "pitch.generated"
    LANDING_GENERATED = "landing.generated"
    PRICING_GENERATED = "pricing.generated"

    # Trial
    TRIAL_STARTED = "trial.started"
    TRIAL_EXPIRED = "trial.expired"
    TRIAL_EXTENDED = "trial.extended"
