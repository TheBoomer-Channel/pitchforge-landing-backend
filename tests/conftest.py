"""Test fixtures for codegen module tests.

Provides mock PlanningOutput with realistic data so every test
has a full planning spec to work with.
Also provides MongoDB test fixtures using mongomock.
"""

import logging
import os as _os
import pytest
from datetime import datetime

logger = logging.getLogger(__name__)

# ── MongoDB test fixtures ──────────────────────────────
#
# Nota: Los tests de integracion con MongoDB requieren un contenedor Docker.
# Para ejecutarlos localmente:
#   docker run -d --name test-mongo -p 27017:27017 mongo:7
#   MONGODB_URL=mongodb://localhost:27017/test_pitch_forge pytest code/backend/tests/

_MONGODB_AVAILABLE = bool(_os.getenv("MONGODB_URL"))

# ── Beanie mock (prevents CollectionWasNotInitialized) ─
# Always applied at module level. Tests use mock stubs for all Beanie operations.
# Real MongoDB init via init_beanie() is NOT used in tests because:
#   1. TestClient creates its own anyio event loop (via BlockingPortal), which
#      conflicts with motor's client binding ("Cannot use AsyncMongoClient in
#      different event loop").
#   2. Even with httpx.AsyncClient + ASGITransport on async tests, pytest-asyncio
#      Mode.AUTO creates separate event loops per test, making session-scoped
#      Beanie init unusable. Switching to Mode.STRICT breaks 200+ other tests.
#
# For route/integration tests that need real MongoDB, use httpx.AsyncClient
# against a LIVE running server (e.g., tests/integration/).

try:
    from unittest.mock import AsyncMock, MagicMock
    from beanie import Document

    # 1. Set mock document settings so get_settings() doesn't raise
    #    CollectionWasNotInitialized (raised when _document_settings is None).
    mock_settings = MagicMock()
    mock_settings.name = "mock_collection"
    mock_settings.union_settings = MagicMock()
    mock_settings.union_settings.name = "mock_union"
    Document._document_settings = mock_settings

    # 2. Mock get_motor_collection for basic CRUD stubs
    def _mock_get_collection(self):
        coll = MagicMock()
        coll.find_one = AsyncMock(return_value=None)
        fmock = MagicMock()
        async def _mock_to_list():
            return []
        fmock.to_list = _mock_to_list
        fmock.sort = MagicMock(return_value=fmock)
        fmock.limit = MagicMock(return_value=fmock)
        fmock.skip = MagicMock(return_value=fmock)
        fmock.project = MagicMock(return_value=fmock)
        fmock.upsert = AsyncMock(return_value=None)
        coll.find = MagicMock(return_value=fmock)
        coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="mock_id"))
        coll.insert = AsyncMock(return_value=MagicMock(inserted_ids=["mock_id"]))
        coll.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        return coll

    Document.get_motor_collection = _mock_get_collection
    logger.info("Patched Beanie Document.get_motor_collection for tests")
except Exception as e:
    logger.warning(f"Could not patch Beanie: {e}")


@pytest.fixture(autouse=True)
def _skip_if_no_mongodb(request):
    """Skip tests marked with @pytest.mark.mongodb.

    The module-level Beanie mock (Document mock) handles basic CRUD but
    cannot cover model field access (e.g. Job.project_id) for all document
    models. Tests that need real Beanie model field resolution should:
      - Be moved to tests/integration/ and run against live Docker API, or
      - Use full init_beanie() with a real MongoDB connection.
    """
    for _ in request.node.iter_markers(name="mongodb"):
        pytest.skip(
            "@pytest.mark.mongodb test skipped: Beanie mock does not cover "
            "all model field access. Use tests/integration/ for real DB tests."
        )
        return


@pytest.fixture
def test_user_data() -> dict:
    """Datos de usuario de prueba para tests MongoDB."""
    return {
        "clerk_user_id": "test_user_001",
        "email": "test@example.com",
        "name": "Test User",
        "tier": "free",
    }


@pytest.fixture
def test_project_data() -> dict:
    """Datos de proyecto de prueba para tests MongoDB."""
    return {
        "title": "Test Project",
        "idea_description": "AI-powered test project for validation",
        "status": "draft",
    }


# ── Codegen test fixtures ─────────────────────────────



@pytest.fixture
def mock_planning():
    """Return a PlanningOutput-compatible dict for testing codegen modules."""
    from app.planning.models import (
        PlanningOutput,
        PRDSpec,
        FunctionalSpec,
        FinancialModel,
        TechnicalSpec,
        PricingTier,
    )

    return PlanningOutput(
        idea="AI-powered code review for indie developers",
        research_summary="Strong market with underserved indie dev segment",
        prd=PRDSpec(
            product_name="CodePeer",
            tagline="AI Code Review for Indie Devs",
            problem_statement="Solo devs ship without reviews and it costs them bugs and reputation",
            proposed_solution="Lightweight AI reviewer that reads your codebase context",
            target_audience=[
                {"segment": "Indie developers", "pain": "No team to review PRs", "size": "12M"},
                {"segment": "Small startups", "pain": "Can't afford senior reviewer time", "size": "5M"},
            ],
            user_stories=[
                "As a solo dev, I want AI review on every PR so I catch bugs early",
                "As a freelancer, I want code quality feedback before client delivery",
            ],
            success_criteria=[
                "1000 active users in 6 months",
                "Review turnaround under 30 seconds",
            ],
            risks=[
                {"risk": "LLM hallucination in reviews", "impact": "high", "mitigation": "Confidence scoring and human-in-the-loop"},
                {"risk": "Competition from GitHub Copilot", "impact": "medium", "mitigation": "Focus on indie-specific features"},
            ],
            assumptions=["Indie devs will pay $9/mo for AI review"],
            dependencies=["OpenAI API", "GitHub API"],
            constraints=["Must work on public repos in free tier"],
            validation_criteria=["10 beta users give positive feedback"],
        ),
        functional=FunctionalSpec(
            user_personas=[
                {"name": "Alex", "role": "Solo indie dev", "goals": ["Ship faster", "Catch bugs"], "pain_points": ["No code review", "Expensive tools"]},
            ],
            core_features=[
                {"id": "F1", "name": "PR Review", "description": "Auto-review pull requests with AI", "priority": "P0", "acceptance_criteria": ["Comments appear on PR within 30s"], "effort": "medium"},
                {"id": "F2", "name": "Hallucination Detector", "description": "Flag code that looks right but is wrong", "priority": "P0", "acceptance_criteria": ["Detects common AI mistakes"], "effort": "high"},
                {"id": "F3", "name": "Dashboard", "description": "View review history and stats", "priority": "P1", "acceptance_criteria": ["Shows review count and trends"], "effort": "low"},
                {"id": "F4", "name": "Security Scanner", "description": "Detect API keys and auth bugs", "priority": "P1", "acceptance_criteria": ["Catches leaked keys"], "effort": "medium"},
                {"id": "F5", "name": "Custom Rules", "description": "Define project-specific review rules", "priority": "P2", "acceptance_criteria": ["Rules are applied to reviews"], "effort": "low"},
            ],
            user_journeys=[
                {"scenario": "First PR review", "steps": ["Install GitHub app", "Open PR", "Receive AI review comments", "Fix issues", "Merge"]},
            ],
            non_functional_reqs=[
                {"category": "Performance", "requirement": "Review under 30 seconds"},
                {"category": "Security", "requirement": "Never store source code"},
            ],
            integration_points=["GitHub API", "GitLab API"],
            data_privacy_notes=["Source code never stored", "Review comments are ephemeral"],
            ui_principles=["Clean and minimal", "Dark mode by default"],
            feature_roadmap=[{"phase": "MVP", "features": ["PR Review", "Hallucination Detector"], "estimate": "4 weeks"}],
        ),
        financial=FinancialModel(
            executive_summary="Freemium model with $9/mo Pro tier. Break-even at 500 users.",
            pricing_tiers=[
                PricingTier(name="Free", price_monthly=0, description="50 reviews/month", features=["Public repos", "Basic review"], target="indie"),
                PricingTier(name="Pro", price_monthly=9, description="Unlimited reviews", features=["Private repos", "Context-aware"], target="indie"),
                PricingTier(name="Team", price_monthly=15, description="Team features", features=["Shared rules", "Slack integration"], target="team"),
            ],
            pricing_rationale="Indie-friendly flat pricing, no per-seat cost",
            unit_economics={"cac": 5, "ltv": 108, "ltv_cac_ratio": 21.6, "gross_margin_pct": 85, "monthly_churn_pct": 5, "payback_period_months": 1},
            cost_breakdown=[{"category": "LLM API", "monthly": 200, "annual": 2400, "notes": "OpenAI API costs"}],
            revenue_projection=[
                {"month": 1, "users": 50, "mrr": 450, "expenses": 500, "profit": -50, "cumulative_profit": -50},
                {"month": 2, "users": 100, "mrr": 900, "expenses": 700, "profit": 200, "cumulative_profit": 150},
                {"month": 3, "users": 200, "mrr": 1800, "expenses": 1000, "profit": 800, "cumulative_profit": 950},
            ],
            break_even_month=2,
            break_even_users=100,
            funding_requirements={"total": 150000, "use_of_funds": {"engineering": 90000, "marketing": 40000, "ops": 20000}},
            key_assumptions=["$9/mo average revenue per user", "5% monthly organic growth"],
        ),
        technical=TechnicalSpec(
            stack_recommendation="FastAPI + React + PostgreSQL + Redis",
            stack_table=[
                {"layer": "Frontend", "technology": "React 18 / Vite", "rationale": "Fast DX, great ecosystem"},
                {"layer": "Backend", "technology": "FastAPI (Python)", "rationale": "Async, type-safe, auto-docs"},
                {"layer": "Database", "technology": "PostgreSQL 16", "rationale": "Reliable, scalable"},
                {"layer": "Cache", "technology": "Redis 7", "rationale": "Job queues, caching"},
            ],
            architecture_notes="Monolith with clear service boundaries for v1",
            data_model=[
                {
                    "entity": "User",
                    "fields": [
                        {"name": "id", "type": "int", "notes": "PK auto"},
                        {"name": "email", "type": "str", "notes": "unique"},
                        {"name": "name", "type": "str"},
                        {"name": "is_active", "type": "bool", "notes": "default true"},
                    ],
                    "relations": ["has_many:Project"],
                },
                {
                    "entity": "Project",
                    "fields": [
                        {"name": "id", "type": "int", "notes": "PK auto"},
                        {"name": "name", "type": "str"},
                        {"name": "repo_url", "type": "url"},
                        {"name": "user_id", "type": "int", "notes": "FK"},
                    ],
                    "relations": ["belongs_to:User"],
                },
            ],
            api_endpoints=[
                {"method": "GET", "path": "/users", "description": "List users", "auth": "required"},
                {"method": "POST", "path": "/users", "description": "Create user", "auth": "public"},
                {"method": "GET", "path": "/users/{id}", "description": "Get user by ID", "auth": "required"},
                {"method": "GET", "path": "/projects", "description": "List projects", "auth": "required"},
                {"method": "POST", "path": "/projects", "description": "Create project", "auth": "required"},
                {"method": "DELETE", "path": "/projects/{id}", "description": "Delete project", "auth": "required"},
            ],
            deployment_architecture="Docker Compose on single VPS for MVP",
            scalability_notes="Add load balancer at 1K concurrent users",
            security_requirements=["JWT auth", "HTTPS only", "Rate limiting"],
            third_party_deps=["OpenAI API", "GitHub API", "Stripe"],
            development_phases=[
                {"phase": "Sprint 1: Foundation", "tasks": ["Set up Docker", "Configure CI/CD", "Create DB schema"], "duration": "1 week"},
                {"phase": "Sprint 2: Core API", "tasks": ["User CRUD", "Auth flow", "Project CRUD"], "duration": "1 week"},
                {"phase": "Sprint 3: Integration", "tasks": ["GitHub webhook", "AI review engine"], "duration": "2 weeks"},
            ],
            estimated_effort="4-6 weeks with 1-2 devs",
            estimated_infra_cost_monthly=50,
        ),
        generated_at=datetime.utcnow(),
    )


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Temporary directory for generated output."""
    d = tmp_path / "output"
    d.mkdir()
    return str(d)
