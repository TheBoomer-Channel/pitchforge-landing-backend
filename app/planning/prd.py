"""PRD Generator — turns ResearchReport into structured Product Requirements Document."""

import json
import logging
from typing import Optional

from app.services.llm import llm
from .models import PRDSpec, FeatureAnchor
from app.research.models import ResearchReport

logger = logging.getLogger(__name__)


def _deterministic_prd(report: ResearchReport) -> PRDSpec:
    """Build PRD from research report data without LLM."""
    features = report.recommended_mvp_features or []
    risks = report.risk_factors or []
    comps = report.competitors[:3] if report.competitors else []

    # TASK-062 — Extract competitive insights
    derived_from = [c.name for c in report.competitors[:5]] if report.competitors else []

    # Use CompetitorAnalyzer results if available
    insights = report.competitive_insights or {}
    table_stakes = insights.get("table_stakes", [])
    differentiators = insights.get("differentiation_gaps", [])
    must_have = insights.get("must_have_features", {})
    pain_summary = insights.get("pain_summary", {})

    # Build pain_point_features from pain summary
    pain_features_list = []
    critical_pains = pain_summary.get("critical", [])[:3]
    for pain in critical_pains:
        pain_features_list.append({
            "pain": pain,
            "feature": f"Solve: {pain[:80]}",
            "competitor": "multiple",
        })

    return PRDSpec(
        product_name=report.idea,
        tagline=report.recommended_positioning or "",
        problem_statement=report.summary or "",
        target_audience=[{"segment": c.target_market or "Unknown", "pain": c.pain_points[0] if c.pain_points else ""} for c in comps],
        proposed_solution=report.summary or "",
        user_stories=[f"As a user, I want to {f.lower()}" for f in features],
        success_criteria=["100 early signups in first month", "3 active users daily", "NPS > 30"],
        risks=[{"risk": r, "impact": "medium", "mitigation": "Monitor and iterate"} for r in risks[:5]],
        assumptions=["Market exists and is growing", "Target users have the problem we think"],
        dependencies=["Stable API from core platform", "Payment processor"],
        constraints=["Bootstrapped budget", "Small team (1-2 devs)", "MVP in 6 weeks"],
        validation_criteria=["Landing page gets >5% conversion", "Waitlist > 50 users"],
        # TASK-062 — Competitive traceability
        derived_from_competitors=derived_from,
        table_stakes_features=table_stakes or must_have.get("table_stakes", []),
        differentiator_features=differentiators or must_have.get("differentiators", []),
        pain_point_features=pain_features_list,
        # TASK-068 — Feature anchors for Spec-Driven Development
        features=[
            FeatureAnchor(
                anchor=f"F{i+1}",
                name=f.split("(")[0].strip() if "(" in f else f,
                description=f,
                priority="P0" if i < 3 else ("P1" if i < 6 else "P2"),
                acceptance_criteria=["Works end-to-end", "User can complete the flow"],
                effort="medium",
            )
            for i, f in enumerate(features)
        ],
    )


async def generate_prd(report: ResearchReport, use_llm: bool = True) -> PRDSpec:
    """Generate full Product Requirements Document using DeepSeek Pro."""
    if not use_llm:
        return _deterministic_prd(report)
    try:
        competitors_text = "\n".join(
            f"- {c.name}: {c.description[:150]} | Pains: {'; '.join(c.pain_points[:2])}" if c.pain_points else f"- {c.name}: {c.description[:150]}"
            for c in report.competitors[:5]
        )
        features_text = "\n".join(f"- {f}" for f in (report.recommended_mvp_features or []))
        risks_text = "\n".join(f"- {r}" for r in (report.risk_factors or []))
        opps_text = "\n".join(f"- {g.gap} ({g.severity})" for g in (report.opportunity_gaps or []))

        prompt = f"""You are a senior product manager. Generate a complete Product Requirements Document (PRD) for the following startup idea.

IDEA: {report.idea}
POSITIONING: {report.recommended_positioning or "Not specified"}
SUMMARY: {report.summary or "Not available"}

=== RESEARCH CONTEXT ===

COMPETITORS:
{competitors_text or "No competitors found"}

RECOMMENDED MVP FEATURES:
{features_text or "No features specified"}

RISK FACTORS:
{risks_text or "No risks identified"}

OPPORTUNITY GAPS:
{opps_text or "No gaps identified"}

=== TASK ===

Produce a structured JSON with EXACTLY this shape (ONLY JSON, no markdown):

{{{{
  "product_name": "Short product name (derived from idea)",
  "tagline": "One-line value proposition",
  "problem_statement": "3-5 sentence description of the problem being solved",
  "target_audience": [
    {{"segment": "Who this is for", "pain": "Their main pain point", "size": "Estimate of segment size"}}
  ],
  "proposed_solution": "2-3 sentence description of the solution",
  "user_stories": [
    "As a [user], I want to [action] so that [benefit]"
  ],
  "success_criteria": [
    "Measurable KPI with target"
  ],
  "risks": [
    {{"risk": "Description of risk", "impact": "high/medium/low", "mitigation": "How to address it"}}
  ],
  "assumptions": [
    "Key assumption being made"
  ],
  "dependencies": [
    "External dependency"
  ],
  "constraints": [
    "Constraint (time, budget, tech, team)"
  ],
  "validation_criteria": [
    "How to validate the product works"
  ]
}}}}

Rules:
- Be specific, not generic. Use the research data.
- Success criteria MUST be measurable (numbers, dates, percentages).
- Target audience MUST have realistic segment sizes.
- Risks MUST map to actual research findings when available.
- Keep it honest — if data is thin, say so in the problem_statement.
- OUTPUT ONLY THE JSON OBJECT."""

        result = await llm.json_pro(prompt, temperature=0.2, max_tokens=4096, timeout=180)
        d = result
        if d:
            prd = PRDSpec(**d)
            # TASK-068 — Ensure features are populated (LLM may not include them)
            if not prd.features:
                prd.features = [
                    FeatureAnchor(
                        anchor=f"F{i+1}",
                        name=s.replace("As a user, I want to ", "").split(" so that")[0].strip()[:80],
                        description=s,
                        priority="P0" if i < 3 else ("P1" if i < 6 else "P2"),
                        acceptance_criteria=["Works end-to-end"],
                    )
                    for i, s in enumerate(prd.user_stories)
                ]
            return prd

        logger.warning("Failed to parse PRD JSON from LLM, using deterministic")
        return _deterministic_prd(report)

    except Exception as e:
        logger.warning(f"PRD LLM failed: {e}, using deterministic fallback")
        return _deterministic_prd(report)
