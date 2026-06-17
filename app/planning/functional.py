"""Functional Spec Generator — features, user flows, UX from research data."""

import json
import logging
from typing import Optional

from app.services.llm import llm
from .models import FunctionalSpec
from app.research.models import ResearchReport

logger = logging.getLogger(__name__)


def _deterministic_functional(report: ResearchReport) -> FunctionalSpec:
    """Build functional spec from research report data without LLM.
    
    TASK-062 — Uses competitive pain points for feature prioritization.
    """
    features = report.recommended_mvp_features or []
    
    # Use CompetitorAnalyzer pain summary for prioritization
    insights = report.competitive_insights or {}
    pain_summary = insights.get("pain_summary", {})
    critical_pains = set(pain_summary.get("critical", []))
    common_pains = set(pain_summary.get("common", []))
    
    # Prioritize: features solving critical pains → P0, common pains → P1, rest → P2
    core_features = []
    for i, f in enumerate(features):
        name = f.split("(")[0].strip() if "(" in f else f
        # Check if this feature relates to any critical/comon pain
        fl = f.lower()
        is_critical = any(p.lower()[:20] in fl for p in critical_pains)
        is_common = any(p.lower()[:20] in fl for p in common_pains)
        if is_critical or i < 2:
            priority = "P0"
        elif is_common or i < 5:
            priority = "P1"
        else:
            priority = "P2"
        core_features.append({
            "id": f"F{i+1}",
            "name": name,
            "description": f,
            "priority": priority,
            "acceptance_criteria": ["Works end-to-end", "User can complete the flow"],
            "effort": "medium",
        })
    
    return FunctionalSpec(
        core_features=core_features,
        user_journeys=[
            {"scenario": "First-time user onboarding", "steps": ["Land on homepage", "Sign up", "Complete profile", "Use core feature"]},
            {"scenario": "Daily active use", "steps": ["Login", "Access main dashboard", "Perform key action", "View results"]},
        ],
        non_functional_reqs=[
            {"category": "performance", "requirement": "Page load < 3s"},
            {"category": "availability", "requirement": "99.5% uptime SLA"},
            {"category": "security", "requirement": "HTTPS, auth, data encryption"},
        ],
        ui_principles=["Mobile-first responsive", "Dark theme", "Minimal clicks to core action"],
    )


async def generate_functional(report: ResearchReport, use_llm: bool = True) -> FunctionalSpec:
    """Generate functional specification using DeepSeek Pro."""
    if not use_llm:
        return _deterministic_functional(report)
    try:
        features_text = "\n".join(f"- {f}" for f in (report.recommended_mvp_features or []))
        competitors_text = "\n".join(
            f"- {c.name}: strengths={c.strengths[:2] if c.strengths else 'N/A'}, weaknesses={c.weaknesses[:2] if c.weaknesses else 'N/A'}"
            for c in report.competitors[:4]
        )

        prompt = f"""You are a senior product designer / UX architect. Generate a complete Functional Specification for the following product.

PRODUCT: {report.idea}
POSITIONING: {report.recommended_positioning or "Not specified"}

=== RESEARCH CONTEXT ===

RECOMMENDED MVP FEATURES:
{features_text or "Not specified"}

COMPETITOR UX INSIGHTS:
{competitors_text or "No competitors found"}

=== TASK ===

Produce a structured JSON with EXACTLY this shape (ONLY JSON, no markdown):

{{{{
  "user_personas": [
    {{{{ "name": "Persona name", "role": "Job title / role", "goals": ["Goal 1", "Goal 2"], "pain_points": ["Pain 1", "Pain 2"], "tech_level": "low/medium/high" }}}}
  ],
  "core_features": [
    {{{{ "id": "F1", "name": "Feature name", "description": "What it does in 1-2 sentences", "priority": "P0", "acceptance_criteria": ["Criterion 1", "Criterion 2"], "effort": "low/medium/high" }}}}
  ],
  "user_journeys": [
    {{{{ "scenario": "End-to-end scenario name", "steps": ["Step 1", "Step 2", "Step 3", "Step 4"] }}}}
  ],
  "non_functional_reqs": [
    {{{{ "category": "performance/security/scalability/usability/reliability", "requirement": "Specific measurable requirement" }}}}
  ],
  "integration_points": [
    "External API or service name"
  ],
  "data_privacy_notes": [
    "Privacy consideration"
  ],
  "ui_principles": [
    "Design principle for the product"
  ],
  "feature_roadmap": [
    {{{{ "phase": "MVP (Weeks 1-4)", "features": ["F1", "F2", "F3"], "estimate": "4 weeks" }}}}
  ]
}}}}

Rules:
- Personas MUST be specific to the target market
- Feature priorities: P0=must have for MVP, P1=important but can wait, P2=nice to have
- Acceptance criteria MUST be testable (pass/fail)
- Non-functional reqs MUST be specific and measurable
- Journeys should cover: onboarding + core action + power user path
- OUTPUT ONLY THE JSON OBJECT."""

        result = await llm.json_pro(prompt, temperature=0.2, max_tokens=4096, timeout=180)
        d = result
        if d:
            return FunctionalSpec(**d)

        logger.warning("Failed to parse Functional JSON, using deterministic")
        return _deterministic_functional(report)

    except Exception as e:
        logger.warning(f"Functional LLM failed: {e}, using deterministic fallback")
        return _deterministic_functional(report)
