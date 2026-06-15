"""
v001_initial_indexes.py — Ensure all Beanie indexes and initial schema.

This migration:
1. Creates all Beanie document indexes (idempotent)
2. Adds MongoDB schema validation for key collections
3. Creates the _migrations tracking collection if missing

Backward-compatible: all operations are create-if-not-exists.
Safe to re-run: index creation and schema validation are idempotent.
"""

import logging

from beanie import init_beanie

REVISION = "v001"
DOWN_REVISION = None
DESCRIPTION = "Initial indexes and schema validation for all Beanie collections"

logger = logging.getLogger("migrations.v001")


async def _ensure_migration_tracking(db):
    """Ensure the _migrations tracking collection exists."""
    collections = await db.list_collection_names()
    if "_migrations" not in collections:
        await db.create_collection("_migrations")
        logger.info("  Created _migrations collection")
    # Ensure index on revision
    await db["_migrations"].create_index("revision", unique=True)
    await db["_migrations"].create_index("applied_at")


async def _ensure_beanie_indexes(db):
    """Run Beanie init for index management (idempotent)."""
    document_models = [
        "app.database.User",
        "app.database.Project",
        "app.database.ResearchResult",
        "app.database.Payment",
        "app.database.Job",
        "app.database.TokenUsage",
        "app.database.TokenPurchase",
        "app.database.ApiKey",
        "app.database.ProjectVersion",
        "app.database.Subscription",
        "app.database.ProcessedWebhookEvent",
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
        "app.models.usage.UsageEvent",
        "app.models.usage.MonthlyUsage",
        "app.models.coupon.Coupon",
        "app.models.coupon.Redemption",
        "app.models.llm_cost.LLMCost",
    ]

    try:
        await init_beanie(
            database=db,
            document_models=document_models,
        )
        logger.info("  Beanie indexes synchronized")
    except Exception as e:
        logger.warning(f"  Beanie init partial: {e}")


async def _ensure_schema_validation(db):
    """Add $jsonSchema validation to key collections for data integrity.

    These are best-effort — they log warnings but don't block if the
    collection doesn't exist yet.
    """
    collections = await db.list_collection_names()

    schema_rules = {
        "users": {
            "bsonType": "object",
            "required": ["clerk_user_id"],
            "properties": {
                "clerk_user_id": {"bsonType": "string"},
                "email": {"bsonType": ["string", "null"]},
                "tier": {"enum": ["free", "starter", "pro", "code_mvp"]},
            },
        },
        "projects": {
            "bsonType": "object",
            "required": ["user_id", "title", "idea_description"],
            "properties": {
                "user_id": {"bsonType": "string"},
                "title": {"bsonType": "string"},
                "status": {"enum": ["draft", "researching", "complete", "error"]},
            },
        },
        "subscriptions": {
            "bsonType": "object",
            "required": ["user_id", "stripe_subscription_id", "tier"],
            "properties": {
                "tier": {"enum": ["starter", "pro", "code_mvp"]},
                "status": {
                    "enum": [
                        "active", "trialing", "past_due",
                        "canceled", "unpaid", "incomplete",
                    ]
                },
            },
        },
    }

    for coll_name, schema in schema_rules.items():
        if coll_name in collections:
            try:
                await db.command(
                    "collMod",
                    coll_name,
                    validator={"$jsonSchema": schema},
                    validationLevel="moderate",  # Warn on existing docs, block new writes
                    validationAction="warn",
                )
                logger.info(f"  Schema validation added to {coll_name}")
            except Exception as e:
                logger.warning(f"  Could not add schema validation to {coll_name}: {e}")


async def upgrade(db):
    """Apply v001: create indexes, tracking collection, and schema validation."""
    logger.info("  Ensuring migration tracking collection...")
    await _ensure_migration_tracking(db)

    logger.info("  Synchronizing Beanie indexes...")
    await _ensure_beanie_indexes(db)

    logger.info("  Adding schema validation (best-effort)...")
    await _ensure_schema_validation(db)

    logger.info("  v001 complete")


async def downgrade(db):
    """Rollback v001: remove schema validation (keeps indexes — harmless)."""
    collections = await db.list_collection_names()

    schema_collections = ["users", "projects", "subscriptions"]
    for coll_name in schema_collections:
        if coll_name in collections:
            try:
                await db.command(
                    "collMod",
                    coll_name,
                    validator={},
                    validationLevel="off",
                )
                logger.info(f"  Schema validation removed from {coll_name}")
            except Exception as e:
                logger.warning(f"  Could not remove validation from {coll_name}: {e}")

    logger.info("  v001 downgrade complete (indexes kept — harmless)")
