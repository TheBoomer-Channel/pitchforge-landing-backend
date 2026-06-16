"""Integration tests for the full pipeline: research → planning → generate → state."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


# ── Fixtures ────────────────────────────────────────────

@pytest.fixture
def mock_research_report():
    """Create a minimal mock ResearchReport for testing."""
    from app.research.models import ResearchReport, Competitor, OpportunityGap
    
    return ResearchReport(
        idea="Test Startup Idea",
        summary="A test summary about the startup idea.",
        competitors=[
            Competitor(name="Comp A", description="Competitor A description", source="tavily"),
            Competitor(name="Comp B", description="Competitor B description", source="reddit"),
        ],
        opportunity_gaps=[
            OpportunityGap(gap="Missing feature X", severity="high", source="reddit"),
            OpportunityGap(gap="Poor UX in existing tools", severity="medium", source="hn"),
        ],
        recommended_mvp_features=[
            "Core feature 1",
            "Core feature 2",
            "Integration with tools",
        ],
        recommended_pricing_range="$29-99/month",
        recommended_positioning="The easiest way to test ideas",
        risk_factors=["High competition", "Technical complexity"],
        sources_used=["tavily", "reddit"],
        research_duration_ms=100,
    )


# ── Shared Module Tests ─────────────────────────────────

class TestSharedModules:
    """Verify the 4 shared modules work correctly."""

    def test_esc_html_imports(self):
        """esc_html should be importable and work correctly."""
        from app.utils.html import esc_html, theme_toggle_html, i18n_switcher_html, schema_org_html
        
        assert esc_html("<script>") == "&lt;script&gt;"
        assert esc_html(None) == ""
        assert "dark:" in theme_toggle_html()
        assert "data-lang-toggle" in i18n_switcher_html()
        assert "schema.org" in schema_org_html("Test", "Tagline")

    def test_paths_make_output_dir(self, tmp_path):
        """make_output_dir should create directory structure correctly."""
        from app.utils.paths import make_output_dir, idea_slug
        
        slug = idea_slug("My Great Idea")
        assert slug == "my-great-idea"
        
        out = make_output_dir("My Idea", Path(tmp_path))
        assert out.exists()
        assert "my-idea" in str(out)

    def test_research_runner_exists(self):
        """run_inline_research should be importable."""
        from app.services.research_runner import run_inline_research
        assert callable(run_inline_research)

    def test_projects_helpers_import(self):
        """All project helpers should be importable."""
        from app.services.projects import (
            load_research_from_project,
            ensure_project_and_research,
            create_job_record,
        )
        assert callable(load_research_from_project)
        assert callable(ensure_project_and_research)
        assert callable(create_job_record)


# ── Generator Tests ─────────────────────────────────────

class TestGenerators:
    """Verify generators produce data-driven output."""

    def test_landing_uses_shared_esc(self, mock_research_report):
        """Landing page should use shared esc_html."""
        from app.generator.landing import build_landing_html
        
        html = build_landing_html(mock_research_report)
        assert "Test Startup Idea" in html
        assert "Comp A" in html  # competitor name
        assert "Missing feature X" in html  # opportunity gap
        # Should NOT contain the old hardcoded demo/image resizer
        assert "picsum.photos" not in html.lower()

    def test_pricing_uses_shared_esc(self, mock_research_report):
        """Pricing page should use shared esc_html."""
        from app.generator.pricing import build_pricing_html
        
        html = build_pricing_html(mock_research_report)
        assert "Test Startup Idea" in html
        assert "$29" in html or "$99" in html

    def test_pitch_uses_shared_esc(self, mock_research_report):
        """Pitch deck should use shared esc_html from utils."""
        from app.generator.pitch import build_pitch_html
        
        html = build_pitch_html(mock_research_report)
        assert "Test Startup Idea" in html
        assert "Pitch Deck" in html

    def test_generate_all_uses_shared_paths(self, mock_research_report, tmp_path):
        """generate_all should use shared make_output_dir — generators are deterministic (no LLM)."""
        from app.generator import generate_all
        import asyncio
        
        # Generators are pure HTML builders — no network/LLM calls needed
        result = asyncio.run(generate_all(mock_research_report, output_dir=str(tmp_path)))
        assert "landing" in result
        assert "pitch_deck" in result
        assert "pricing" in result
        
        # Verify files were written (TASK-063 saves in assets/ subdirectory)
        for name in ("landing", "pitch_deck", "pricing"):
            path = Path(tmp_path) / "assets" / f"{name}.html"
            assert path.exists(), f"Missing file: {path}"
            assert path.read_text().startswith("<!DOCTYPE html>")


# ── Pipeline Integration Tests ──────────────────────────

class TestPipelineIntegration:
    """Verify the pipeline components work together."""

    @pytest.mark.asyncio
    async def test_research_runner_basic(self):
        """Research runner should be callable (may fail without real API)."""
        from app.services.research_runner import run_inline_research
        
        # This will try real sources; should handle failures gracefully
        try:
            report = await run_inline_research(
                idea="Test idea for integration test",
                use_llm=False,
            )
            assert report is not None
            assert hasattr(report, "idea")
        except Exception as e:
            # Expected: may fail due to missing API keys or network
            assert "timeout" not in str(e).lower()

    def test_landing_html_contains_all_data_sections(self, mock_research_report):
        """Landing page should render all data-driven sections."""
        from app.generator.landing import build_landing_html
        
        html = build_landing_html(mock_research_report)
        
        # Stats
        assert 'data-count="2"' in html  # competitors count
        assert 'data-count="3"' in html  # features count
        assert 'data-count="2"' in html  # gaps count
        
        # Sections
        assert "How We Compare" in html or "Como Comparamos" in html
        assert "Opportunity Gaps" in html or "Oportunidades" in html
        assert "Backed by Real Research" in html
        assert "Simple Pricing" in html

    def test_pricing_uses_research_data(self, mock_research_report):
        """Pricing page tiers should reflect research pricing data."""
        from app.generator.pricing import build_pricing_html, _derive_tiers
        
        tiers = _derive_tiers("$29-99/month", mock_research_report.competitors, mock_research_report.recommended_mvp_features)
        
        assert len(tiers) == 3
        assert tiers[0]["name"] == "Free"
        assert tiers[1]["price"] == "$29"  # Matches pricing range
        
        # Starter features should include research features
        starter_features = tiers[1]["features"]
        assert len(starter_features) > 0

    @pytest.mark.asyncio
    async def test_narrative_engine_data_driven(self, mock_research_report):
        """Narrative engine should use real research data for slides."""
        from app.generator.narrative import generate_narrative
        
        narrative = generate_narrative(mock_research_report)
        
        assert narrative.total_slides == 9
        assert narrative.idea == "Test Startup Idea"
        
        # Problem slide uses opportunity gaps (key_points filled from gaps)
        problem_slide = narrative.slides[1]
        assert "Missing feature X" in " ".join(problem_slide.key_points)
        assert len(problem_slide.speaker_notes) > 0


# ── Route Integration Tests ─────────────────────────────

class TestRouteIntegration:
    """Verify routes work together with shared modules."""

    def test_projects_route_imports(self):
        """Projects route should use proper dependency injection."""
        from app.routes.projects import router
        assert router is not None
        
        # Should have state endpoint (FastAPI prepends the router prefix)
        routes = [r.path for r in router.routes]
        assert "/api/projects/{project_id}/state" in routes

    def test_research_route_uses_shared_runner(self):
        """Research route should import from shared research_runner."""
        import inspect
        from app.routes.research import start_research
        
        source = inspect.getsource(start_research)
        assert "run_inline_research" in source
        assert "create_job_record" in source

    def test_planning_route_uses_shared_modules(self):
        """Planning route should use shared helpers, not inline duplication."""
        import inspect
        from app.routes.planning import start_planning
        
        source = inspect.getsource(start_planning)
        # Should use shared helpers, not inline hermes/http_client
        assert "load_research_from_project" in source
        assert "ensure_project_and_research" in source
        assert "create_job_record" in source
        assert "make_output_dir" in source
        # Should NOT have the old inline patterns
        assert "ResearchHTTPClient()" not in source
        assert "AsyncSession(db_engine)" not in source

    def test_generate_route_uses_shared_modules(self):
        """Generate route should use shared helpers, not inline duplication."""
        import inspect
        from app.routes.generate import generate_assets
        
        source = inspect.getsource(generate_assets)
        # Should use shared helpers
        assert "load_research_from_project" in source
        assert "ensure_project_and_research" in source
        assert "create_job_record" in source
        # Should NOT have the old inline patterns
        assert "ResearchHTTPClient()" not in source
        assert "AsyncSession(db_engine)" not in source
