"""Technical Spec Generator — stack, architecture, data model from research data."""

import json
import logging
from typing import Optional

from app.services.llm import llm
from .models import TechnicalSpec
from app.research.models import ResearchReport

logger = logging.getLogger(__name__)

# ── Module-level entity patterns: (keywords, entity_name, fields, relations) ──
_ENTITY_PATTERNS: list[tuple[list[str], str, list[dict], list[str]]] = [
    (["subscription", "plan", "pricing", "tier", "billing"],
     "Subscription",
     [{"name": "id", "type": "uuid"}, {"name": "user_id", "type": "relation"}, {"name": "plan", "type": "string"}, {"name": "status", "type": "string"}, {"name": "current_period_end", "type": "datetime"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
    (["organization", "team", "workspace", "company"],
     "Organization",
     [{"name": "id", "type": "uuid"}, {"name": "name", "type": "string"}, {"name": "slug", "type": "string"}, {"name": "owner_id", "type": "relation"}, {"name": "created_at", "type": "datetime"}],
     ["HasMany: User", "HasMany: Project"]),
    (["project", "repository", "repo"],
     "Project",
     [{"name": "id", "type": "uuid"}, {"name": "name", "type": "string"}, {"name": "description", "type": "string"}, {"name": "owner_id", "type": "relation"}, {"name": "status", "type": "string"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User", "HasMany: Task"]),
    (["task", "todo", "issue"],
     "Task",
     [{"name": "id", "type": "uuid"}, {"name": "title", "type": "string"}, {"name": "description", "type": "string"}, {"name": "assignee_id", "type": "relation"}, {"name": "status", "type": "string"}, {"name": "priority", "type": "string"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User", "BelongsTo: Project"]),
    (["payment", "invoice", "transaction", "receipt"],
     "Payment",
     [{"name": "id", "type": "uuid"}, {"name": "user_id", "type": "relation"}, {"name": "amount", "type": "float"}, {"name": "currency", "type": "string"}, {"name": "status", "type": "string"}, {"name": "stripe_payment_id", "type": "string"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
    (["notification", "alert", "in-app"],
     "Notification",
     [{"name": "id", "type": "uuid"}, {"name": "user_id", "type": "relation"}, {"name": "type", "type": "string"}, {"name": "title", "type": "string"}, {"name": "body", "type": "text"}, {"name": "read", "type": "boolean"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
    (["file", "upload", "attachment", "document", "image"],
     "File",
     [{"name": "id", "type": "uuid"}, {"name": "name", "type": "string"}, {"name": "url", "type": "string"}, {"name": "size_bytes", "type": "int"}, {"name": "mime_type", "type": "string"}, {"name": "owner_id", "type": "relation"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
    (["integration", "webhook", "connect"],
     "Integration",
     [{"name": "id", "type": "uuid"}, {"name": "user_id", "type": "relation"}, {"name": "provider", "type": "string"}, {"name": "config", "type": "json"}, {"name": "status", "type": "string"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
    (["comment", "review", "feedback"],
     "Comment",
     [{"name": "id", "type": "uuid"}, {"name": "author_id", "type": "relation"}, {"name": "body", "type": "text"}, {"name": "parent_type", "type": "string"}, {"name": "parent_id", "type": "uuid"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
    (["analytics", "dashboard", "report", "metrics", "stats"],
     "AnalyticsEvent",
     [{"name": "id", "type": "uuid"}, {"name": "user_id", "type": "relation"}, {"name": "event", "type": "string"}, {"name": "properties", "type": "json"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
    (["api key", "apikey", "credential"],
     "ApiKey",
     [{"name": "id", "type": "uuid"}, {"name": "user_id", "type": "relation"}, {"name": "name", "type": "string"}, {"name": "key_hash", "type": "string"}, {"name": "last_used", "type": "datetime"}, {"name": "expires_at", "type": "datetime"}, {"name": "created_at", "type": "datetime"}],
     ["BelongsTo: User"]),
]

_ARTICLES = frozenset({"a", "an", "the"})


def _deterministic_technical(report: ResearchReport) -> TechnicalSpec:
    """Build technical spec from research report data without LLM.
    
    TASK-062-filled — data_model and api_endpoints derived from features.
    """
    features = report.recommended_mvp_features or []
    all_text = " ".join(features).lower() + " " + report.summary.lower()

    data_model = []
    entities_seen = set()

    # Always include User and Session as base
    data_model.append({
        "entity": "User",
        "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "email", "type": "string"},
            {"name": "name", "type": "string"},
            {"name": "avatar_url", "type": "string"},
            {"name": "role", "type": "string", "notes": "admin/member"},
            {"name": "created_at", "type": "datetime"},
            {"name": "updated_at", "type": "datetime"},
        ],
        "relations": ["HasMany: Session"],
    })
    entities_seen.add("user")
    data_model.append({
        "entity": "Session",
        "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "user_id", "type": "relation"},
            {"name": "token_hash", "type": "string"},
            {"name": "expires_at", "type": "datetime"},
            {"name": "created_at", "type": "datetime"},
        ],
        "relations": ["BelongsTo: User"],
    })
    entities_seen.add("session")

    for keywords, entity_name, default_fields, default_relations in _ENTITY_PATTERNS:
        if entity_name.lower() in entities_seen:
            continue
        if any(kw in all_text for kw in keywords):
            data_model.append({
                "entity": entity_name,
                "fields": default_fields,
                "relations": default_relations,
            })
            entities_seen.add(entity_name.lower())

    # If fewer than 4 entities found, add a generic one from the product domain
    if len(data_model) < 4:
        idea_words = report.idea.split() if report.idea else []
        # Skip leading articles (a, an, the) to avoid single-letter entity names
        core_name = "Resource"
        for w in idea_words:
            if w.lower() not in _ARTICLES:
                core_name = w.capitalize()
                break
        data_model.append({
            "entity": core_name,
            "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "name", "type": "string"},
                {"name": "description", "type": "string"},
                {"name": "owner_id", "type": "relation"},
                {"name": "status", "type": "string"},
                {"name": "created_at", "type": "datetime"},
            ],
            "relations": ["BelongsTo: User"],
        })
        entities_seen.add(core_name.lower())

    # ── Derive API endpoints from data model + features ──
    api_endpoints = [
        {"method": "POST", "path": "/api/v1/auth/register", "description": "Register a new user account", "auth": "public", "rate_limit": "10/min"},
        {"method": "POST", "path": "/api/v1/auth/login", "description": "Login and receive JWT tokens", "auth": "public", "rate_limit": "20/min"},
        {"method": "POST", "path": "/api/v1/auth/refresh", "description": "Refresh access token", "auth": "public", "rate_limit": "30/min"},
        {"method": "GET", "path": "/api/v1/users/me", "description": "Get current user profile", "auth": "required"},
        {"method": "PATCH", "path": "/api/v1/users/me", "description": "Update current user profile", "auth": "required"},
        {"method": "DELETE", "path": "/api/v1/users/me", "description": "Delete account (GDPR)", "auth": "required"},
    ]

    for entity in data_model:
        name = entity["entity"]
        slug = name.lower().replace(" ", "-")
        # Skip User/Session — already covered
        if slug in ("user", "session"):
            continue
        # Standard CRUD
        api_endpoints.append({
            "method": "GET",
            "path": f"/api/v1/{slug}s",
            "description": f"List {name}s for current user",
            "auth": "required",
        })
        api_endpoints.append({
            "method": "POST",
            "path": f"/api/v1/{slug}s",
            "description": f"Create a new {name}",
            "auth": "required",
        })
        api_endpoints.append({
            "method": "GET",
            "path": f"/api/v1/{slug}s/{{id}}",
            "description": f"Get {name} by ID",
            "auth": "required",
        })
        api_endpoints.append({
            "method": "PATCH",
            "path": f"/api/v1/{slug}s/{{id}}",
            "description": f"Update {name}",
            "auth": "required",
        })
        api_endpoints.append({
            "method": "DELETE",
            "path": f"/api/v1/{slug}s/{{id}}",
            "description": f"Delete {name}",
            "auth": "required",
        })

    # Health + webhook endpoints always present
    api_endpoints.append({
        "method": "GET", "path": "/api/v1/health", "description": "Health check", "auth": "public",
    })
    if any(kw in all_text for kw in ["webhook", "web hook"]):
        api_endpoints.append({
            "method": "POST", "path": "/api/v1/webhooks/{provider}", "description": "Receive webhook from external service", "auth": "public (HMAC verified)",
        })

    return TechnicalSpec(
        stack_recommendation=f"Modern web stack: React + FastAPI + PostgreSQL deployed on VPS/Docker",
        stack_table=[
            {"layer": "Frontend", "technology": "React + Vite + Tailwind", "rationale": "Fast dev, great DX, responsive"},
            {"layer": "Backend", "technology": "FastAPI (Python)", "rationale": "Async, auto-docs, strong typing"},
            {"layer": "Database", "technology": "PostgreSQL", "rationale": "Reliable, ACID, great ecosystem"},
            {"layer": "Auth", "technology": "Supabase Auth / Firebase", "rationale": "Quick setup, social login"},
            {"layer": "Hosting", "technology": "VPS (Coolify / Docker)", "rationale": "Full control, lower cost at scale"},
            {"layer": "Payments", "technology": "Stripe", "rationale": "Best API, subscriptions, tax handling"},
        ],
        architecture_notes="Standard 3-tier: Browser → API (FastAPI) → Database. Background jobs via Arq/Redis.",
        data_model=data_model,
        api_endpoints=api_endpoints,
        deployment_architecture="Docker Compose on single VPS. API + Worker + Redis + DB. Coolify for management.",
        scalability_notes="Start on single $25 VPS. Scale horizontally when load > 1000 DAU: add worker nodes, read replicas.",
        security_requirements=[
            "HTTPS everywhere (Let's Encrypt via Coolify)",
            "JWT-based auth with refresh tokens",
            "Rate limiting on public endpoints",
            "Input validation on all API endpoints",
            "SQL injection prevention (parameterized queries)",
            "CORS restricted to own domain",
        ],
        third_party_deps=[
            "Stripe (payments)",
            "Supabase or Firebase (auth)",
            "Redis (queues + caching)",
            "Cloudflare (DNS + CDN)",
            "Sentry (error tracking)",
            "Postmark or SendGrid (email)",
        ],
        development_phases=[
            {"phase": "Sprint 1: Foundation", "tasks": ["Project setup", "DB schema", "Auth flow", "Basic API"], "duration": "1 week"},
            {"phase": "Sprint 2: Core feature", "tasks": ["Main feature API", "Frontend pages", "Integration"], "duration": "2 weeks"},
            {"phase": "Sprint 3: Polish", "tasks": ["Payments", "Email", "Testing", "Deploy"], "duration": "1 week"},
        ],
        estimated_effort="4-6 weeks for MVP with 1-2 developers",
        estimated_infra_cost_monthly=50.0,
    )


async def generate_technical(report: ResearchReport, use_llm: bool = True) -> TechnicalSpec:
    """Generate technical specification using DeepSeek Pro."""
    if not use_llm:
        return _deterministic_technical(report)
    try:
        features_text = "\n".join(f"- {f}" for f in (report.recommended_mvp_features or []))

        prompt = f"""You are a senior software architect. Generate a complete Technical Specification for the following product.

PRODUCT: {report.idea}
POSITIONING: {report.recommended_positioning or "Not specified"}

=== PRODUCT CONTEXT ===

MVP FEATURES:
{features_text or "Not specified"}

=== TASK ===

Produce a structured JSON with EXACTLY this shape (ONLY JSON, no markdown):

{{{{
  "stack_recommendation": "1-2 sentence overall stack summary",
  "stack_table": [
    {{{{"layer": "Frontend", "technology": "Technology choice", "rationale": "Why this choice"}}}}
  ],
  "architecture_notes": "2-3 sentences describing the architecture pattern",
  "data_model": [
    {{{{"entity": "Entity name", "fields": [{{"name": "field_name", "type": "string/int/float/boolean/relation", "notes": "optional notes"}}], "relations": ["HasMany: OtherEntity"]}}}}
  ],
  "api_endpoints": [
    {{{{"method": "GET", "path": "/api/v1/resource", "description": "What this endpoint does", "auth": "required/optional/public", "rate_limit": "Optional rate limit"}}}}
  ],
  "deployment_architecture": "Describe deploy strategy — Docker, Coolify, CI/CD",
  "scalability_notes": "How to scale from 10 to 10000 users",
  "security_requirements": [
    "Specific security requirement"
  ],
  "third_party_deps": [
    "Dependency name — what it does"
  ],
  "development_phases": [
    {{{{"phase": "Phase name", "tasks": ["Task 1", "Task 2"], "duration": "Duration estimate"}}}}
  ],
  "estimated_effort": "Total effort estimate for MVP",
  "estimated_infra_cost_monthly": 50.0
}}}}

Rules:
- Be specific with technology choices and rationales
- API endpoints should map directly to MVP features
- Data model should have 4-8 core entities
- Development phases should be concrete, not generic
- Cost estimates should be REALISTIC (starting small)
- Prefer open-source and free-tier where possible
- For bootstrapped: prefer VPS over cloud (lower cost)
- OUTPUT ONLY THE JSON OBJECT."""

        result = await llm.json_pro(prompt, temperature=0.2, max_tokens=4096, timeout=180)
        d = result
        if d:
            return TechnicalSpec(**d)

        logger.warning("Failed to parse Technical JSON, using deterministic")
        return _deterministic_technical(report)

    except Exception as e:
        logger.warning(f"Technical LLM failed: {e}, using deterministic fallback")
        return _deterministic_technical(report)
