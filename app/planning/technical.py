"""Technical Spec Generator — stack, architecture, data model from research data."""

import json
import logging
from typing import Optional

from app.services.llm import llm
from .models import TechnicalSpec
from app.research.models import ResearchReport

logger = logging.getLogger(__name__)


def _deterministic_technical(report: ResearchReport) -> TechnicalSpec:
    """Build technical spec from research report data without LLM."""
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


async def generate_technical(report: ResearchReport) -> TechnicalSpec:
    """Generate technical specification using DeepSeek Pro."""
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
