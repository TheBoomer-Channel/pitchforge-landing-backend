"""MongoDB database — Beanie ODM (async) for all project models.

Replaces previous SQLAlchemy/SQLite setup with MongoDB via Beanie + Motor.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import Field

from .config import settings

logger = logging.getLogger(__name__)


# ── Connection ─────────────────────────────────────────

client: Optional[AsyncIOMotorClient] = None


async def init_db():
    """Initialize MongoDB connection and Beanie ODM."""
    global client
    if not settings.MONGODB_URL:
        logger.warning("No MONGODB_URL configured — running without database")
        return

    try:
        client = AsyncIOMotorClient(settings.MONGODB_URL)
        database = client[settings.MONGODB_DB_NAME]

        await init_beanie(
            database=database,
            document_models=[
                "app.database.User",
                "app.database.Project",
                "app.database.ResearchResult",
                "app.database.Payment",
                "app.database.Job",
                "app.database.TokenUsage",
                "app.database.TokenPurchase",
                "app.database.ApiKey",
                "app.database.ProjectVersion",
                "app.models.legal.LegalDocument",
                "app.models.legal.UserLegalAcceptance",
                "app.models.legal.ConsentRecord",
                "app.models.legal.DataDeletionRequest",
                "app.models.legal.DataExportRequest",
                "app.models.email_verification.EmailVerification",
                "app.models.two_factor.TwoFactorSecret",
                "app.models.two_factor.TwoFactorAttempt",
                "app.models.audit.AuditEvent",
                "app.services.audit_service._AuditCounter",
                "app.database.Subscription",
                "app.database.ProcessedWebhookEvent",
                "app.models.usage.UsageEvent",
                "app.models.usage.MonthlyUsage",
                "app.models.coupon.Coupon",
                "app.models.coupon.Redemption",
                "app.models.llm_cost.LLMCost",
                "app.email_lifecycle.models.EmailEvent",
                "app.email_lifecycle.models.UnsubscribeToken",
                "app.referrals.models.Referral",
                "app.webhooks.models.WebhookEndpoint",
                "app.webhooks.models.WebhookDelivery",
                "app.models.marketplace.Template",
                "app.models.marketplace.TemplatePurchase",
            ],
        )
        logger.info(f"MongoDB connected: {settings.MONGODB_DB_NAME}")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise


async def close_db():
    """Close MongoDB connection."""
    global client
    if client:
        client.close()
        client = None
        logger.info("MongoDB connection closed")


# ── Mixins ─────────────────────────────────────────────


class TimestampMixin:
    """Auto-timestamp fields for created_at/updated_at."""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)


# ── Project ────────────────────────────────────────────


class Project(TimestampMixin, Document):
    """A startup project — the central entity of the app.
    
    TASK-061: Extended with pipeline tracking and output paths.
    Every feature (Research, Planning, CodeGen, Assets) updates its step here.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Custom string ID
    user_id: str  # Clerk user ID (string)
    title: str
    idea_description: str
    target_market: Optional[str] = None
    business_model: Optional[str] = None
    status: str = "draft"  # draft/researching/complete/error

    # TASK-061 — Pipeline state per feature step
    pipeline: dict = Field(default_factory=lambda: {
        "research": {"status": "pending", "job_id": None, "completed_at": None},
        "planning": {"status": "pending", "job_id": None, "completed_at": None},
        "codegen":  {"status": "pending", "job_id": None, "completed_at": None},
        "assets":   {"status": "pending", "job_id": None, "completed_at": None},
    })

    # TASK-061 — Output paths for generated content
    research_result_id: Optional[str] = None
    planning_output_dir: Optional[str] = None
    codegen_output_dir: Optional[str] = None
    assets_output_dir: Optional[str] = None

    # GitHub integration
    github_repo_url: Optional[str] = None
    github_token: Optional[str] = None
    github_branch: str = "main"

    class Settings:
        name = "projects"
        indexes = [
            "user_id",
            [("user_id", 1), ("created_at", -1)],
        ]


# ── Research Result ────────────────────────────────────


class ResearchResult(TimestampMixin, Document):
    """Stored research report linked to a project."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Custom string ID
    project_id: Indexed(str, unique=True)
    report_json: Optional[dict] = None
    report_markdown: Optional[str] = None
    summary: Optional[str] = None
    sources_used: Optional[list] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None

    class Settings:
        name = "research_results"
        indexes = ["project_id"]


# ── Payment (Stripe) ───────────────────────────────────


class Payment(TimestampMixin, Document):
    """Stripe payment records."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Custom string ID
    user_id: str  # Clerk user ID (string)
    project_id: Optional[str] = None
    tier: str
    amount: int = 0  # cents
    currency: str = "eur"
    stripe_session_id: Optional[str] = None
    status: str = "pending"  # pending/completed/expired

    class Settings:
        name = "payments"
        indexes = ["user_id", "stripe_session_id"]


# ── Subscription (TASK-016) ─────────────────────────────


class Subscription(Document):
    """Mirror of a Stripe subscription, for fast lookups without hitting Stripe.

    One row per active subscription. Replaces/extends the Payment table
    for recurring billing.
    """

    user_id: Indexed(str)
    stripe_customer_id: Indexed(str)
    stripe_subscription_id: Indexed(str, unique=True)
    tier: str  # starter / pro / code_mvp
    status: str = "active"  # active / trialing / past_due / canceled / unpaid / incomplete
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    canceled_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None

    class Settings:
        name = "subscriptions"
        indexes = [
            "user_id",
            "stripe_customer_id",
            "stripe_subscription_id",
            [("user_id", 1), ("status", 1)],
        ]


# ── Processed Webhook Events (TASK-016 — idempotency) ───


class ProcessedWebhookEvent(Document):
    """Idempotency table for Stripe webhooks.

    One row per stripe_event_id that we have successfully processed.
    Stripe may retry on 5xx; a unique index on stripe_event_id makes
    inserts idempotent.
    """

    stripe_event_id: Indexed(str, unique=True)
    event_type: str
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: Optional[str] = None

    class Settings:
        name = "processed_webhook_events"
        indexes = [
            "stripe_event_id",
            [("processed_at", -1)],
        ]


# ── Job (background task tracking) ─────────────────────


class Job(TimestampMixin, Document):
    """Background job tracking (research, planning, codegen)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Custom string ID
    project_id: Optional[str] = None
    type: str  # research/planning/codegen
    status: str = "pending"  # pending/running/complete/error
    progress: Optional[float] = 0.0
    logs: Optional[list] = Field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    worker_id: Optional[str] = None

    class Settings:
        name = "jobs"
        indexes = [
            "project_id",
            [("project_id", 1), ("created_at", -1)],
        ]


# ── Token Usage (code generation billing) ──────────────


class TokenUsage(TimestampMixin, Document):
    """Tracks token consumption per task."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Custom string ID
    user_id: str  # Clerk user ID (string)
    project_id: Optional[str] = None
    task_id: str
    tokens_consumed: int = 0
    description: str = ""

    class Settings:
        name = "token_usage"
        indexes = [
            "user_id",
            [("user_id", 1), ("created_at", -1)],
        ]


class TokenPurchase(TimestampMixin, Document):
    """Token purchases via Stripe."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Custom string ID
    user_id: str  # Clerk user ID (string)
    amount: float = 0.0
    tokens_added: int = 0
    stripe_session_id: Optional[str] = None

    class Settings:
        name = "token_purchases"
        indexes = ["user_id"]


# ── User (metadata — tier stored here, auth via Clerk) ─


class User(Document):
    """User metadata synced from Clerk. Auth is managed by Clerk entirely.

    This collection stores app-specific fields (tier, usage counters)
    that are NOT stored in Clerk.
    """
    clerk_user_id: Indexed(str, unique=True)  # Matches Clerk's user ID
    email: Optional[str] = None
    name: Optional[str] = None
    tier: str = "free"  # free/starter/pro/code_mvp
    stripe_customer_id: Optional[str] = None
    research_count_today: int = 0
    projects_this_month: int = 0
    last_research_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # TASK-022 — email verification
    email_verified: bool = False
    email_verified_at: Optional[datetime] = None

    # TASK-011 — 2FA / MFA
    two_factor_enabled: bool = False
    two_factor_enabled_at: Optional[datetime] = None
    two_factor_forced: bool = False  # true for admins; set manually

    # TASK-018 — Free trial
    trial_started_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None
    trial_extended: bool = False

    # TASK-040 — Email lifecycle
    email_opt_out: bool = False

    # TASK-042 — Referral program
    referral_code: Optional[str] = None
    referred_by: Optional[str] = None

    class Settings:
        name = "users"
        indexes = [
            "clerk_user_id",
            "email",
            "referral_code",
        ]


# ── Project Version (snapshot history) ─────────────────

class ProjectVersion(TimestampMixin, Document):
    """A snapshot of a project at a point in time."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    version: int = 1
    label: str = ""  # e.g., "Initial research", "After planning"
    snapshot: dict = Field(default_factory=dict)  # Full project state
    files: list[dict] = Field(default_factory=list)  # Generated files at this version
    size_bytes: int = 0

    class Settings:
        name = "project_versions"
        indexes = [
            [("project_id", 1), ("version", -1)],
        ]


# ── API Key (for MCP / LLM access) ─────────────────────


class ApiKey(TimestampMixin, Document):
    """Per-user API keys for programmatic access."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))  # Custom string ID
    user_id: str  # Clerk user ID (string)
    name: str = "Default"
    key_prefix: str  # e.g., "sf_a1b2c3d4"
    key_hash: str  # bcrypt hash
    last_used_at: Optional[datetime] = None
    is_active: bool = True

    class Settings:
        name = "api_keys"
        indexes = [
            "user_id",
            "key_prefix",
        ]
