"""Legal & GDPR models — TASK-010 + TASK-012.

  * LegalDocument: in-DB index of available legal docs (slug, version,
    effective_at, requires_acceptance). The actual markdown content is
    served from `content/legal/{version}/{slug}.md` on disk.
  * UserLegalAcceptance: timestamped record that a user accepted a given
    (doc, version) pair. Indexed on (user_id, doc_slug).
  * ConsentRecord: GDPR consent for specific data processing purposes
    (marketing, analytics, third-party integrations). Distinct from
    CookieBanner consent (which is localStorage-only) so it persists
    across devices and is auditable server-side.
  * DataDeletionRequest: 30-day soft delete with cancellation window,
    followed by hard delete via background job.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


# ── Legal Document ──────────────────────────────────────


class LegalDocument(Document):
    """An index of a legal document version.

    The actual markdown content lives on disk at
    `content/legal/{version}/{slug}.md`. We keep a small index in DB
    so the API can answer "what is the current version of each doc?"
    without hitting the filesystem.
    """

    slug: Indexed(str, unique=True)  # e.g., "terms", "privacy", "cookies", "aup"
    version: str  # semver, e.g., "1.0.0"
    title: str  # human-readable
    effective_at: datetime
    requires_acceptance: bool = True
    superseded_at: Optional[datetime] = None  # set when a newer version is published
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "legal_documents"
        indexes = [
            "slug",
            [("slug", 1), ("version", -1)],
            [("slug", 1), ("effective_at", -1)],
        ]


# ── User Legal Acceptance ──────────────────────────────


class UserLegalAcceptance(Document):
    """A user's acceptance of a (doc, version) pair.

    Idempotent: a user can only have one active acceptance per
    (user_id, doc_slug, version) tuple. Re-acceptance is recorded as
    a new row (so we have a full audit trail).
    """

    user_id: Indexed(str)
    doc_slug: str
    version: str
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    source: str = "signup"  # signup / re_prompt / settings / settings_modal

    class Settings:
        name = "user_legal_acceptances"
        indexes = [
            "user_id",
            [("user_id", 1), ("doc_slug", 1)],
            [("user_id", 1), ("doc_slug", 1), ("version", 1)],
        ]


# ── Consent Record (GDPR Art. 7) ───────────────────────


class ConsentRecord(Document):
    """GDPR Art. 7 record of consent for specific processing purposes.

    Distinct from the cookie banner's localStorage consent. This is the
    auditable, server-side record required by GDPR. It captures both
    "yes" and "no" answers (a withdrawal is a record too).
    """

    user_id: Indexed(str)
    purpose: str  # e.g., "marketing_email", "product_analytics", "third_party_share"
    granted: bool
    version: str = "1.0.0"  # bump when the purpose or its scope changes
    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    method: str = "settings"  # signup / settings / email_link / api

    class Settings:
        name = "consent_records"
        indexes = [
            "user_id",
            [("user_id", 1), ("purpose", 1)],
        ]


# ── Data Deletion Request (GDPR Art. 17) ──────────────


class DataDeletionRequest(Document):
    """30-day soft delete with cancellation window.

    - status = "pending"   → user can cancel within 30 days
    - status = "cancelled" → user changed their mind
    - status = "completed" → hard delete has been performed
    - status = "failed"    → background job failed; manual intervention needed
    """

    user_id: Indexed(str, unique=True)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scheduled_hard_delete_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30)
    )
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    status: str = "pending"  # pending / cancelled / completed / failed
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    notes: Optional[str] = None

    class Settings:
        name = "data_deletion_requests"
        indexes = [
            "user_id",
            "status",
            [("status", 1), ("scheduled_hard_delete_at", 1)],
        ]


# ── Data Export (GDPR Art. 20 — Right to Portability) ──


class DataExportRequest(Document):
    """Records each export download (rate-limited, audit-trailed)."""

    user_id: Indexed(str)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    file_size_bytes: Optional[int] = None
    download_count: int = 0
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=7)
    )
    status: str = "pending"  # pending / ready / expired / failed
    ip: Optional[str] = None

    class Settings:
        name = "data_export_requests"
        indexes = [
            "user_id",
            [("user_id", 1), ("requested_at", -1)],
        ]
