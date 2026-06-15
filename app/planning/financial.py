"""Financial Model Generator — pricing, unit economics, projections from research data."""

import json
import logging
from typing import Optional

from app.services.llm import llm
from .models import FinancialModel, PricingTier
from app.research.models import ResearchReport

logger = logging.getLogger(__name__)


def _deterministic_financial(report: ResearchReport) -> FinancialModel:
    """Build financial model from research data without LLM."""
    pricing_range = report.recommended_pricing_range or "$29-99/month"
    
    # TASK-062 — Use competitor pricing analysis if available
    insights = report.competitive_insights or {}
    pricing_landscape = insights.get("pricing_landscape", {})
    
    # Derive pricing tiers from competitor data
    tiers = [
        PricingTier(name="Free", price_monthly=0, description="Get started", features=["Basic features", "1 project"], target="indie"),
    ]
    
    if pricing_landscape.get("range"):
        r = pricing_landscape["range"]
        median = r.get("median", 49)
        max_price = r.get("max", 99)
        starter_price = max(9, int(median * 0.6)) if median else 29
        pro_price = max(starter_price * 2, int(median * 1.5)) if median else 99
        tiers = [
            PricingTier(name="Free", price_monthly=0, description="Get started", features=["Basic features", "1 project"], target="indie"),
            PricingTier(name="Starter", price_monthly=starter_price, price_yearly=starter_price * 10, description="For indie makers", features=["All features", "5 projects", "Email support"], target="indie"),
            PricingTier(name="Pro", price_monthly=pro_price, price_yearly=pro_price * 10, description="For teams", features=["Unlimited projects", "Priority support", "API access"], target="team"),
        ]
    else:
        tiers = [
            PricingTier(name="Free", price_monthly=0, description="Get started", features=["Basic features", "1 project"], target="indie"),
            PricingTier(name="Starter", price_monthly=29, price_yearly=290, description="For indie makers", features=["All features", "5 projects", "Email support"], target="indie"),
            PricingTier(name="Pro", price_monthly=99, price_yearly=990, description="For teams", features=["Unlimited projects", "Priority support", "API access"], target="team"),
        ]
    
    # Competitor-based rationale
    comp_count = len(pricing_landscape.get("competitors", []))
    if comp_count:
        pricing_rationale = (
            f"Based on analysis of {comp_count} competitors. "
            f"Market range: ${pricing_landscape['range'].get('min', '?')}-${pricing_landscape['range'].get('max', '?')}. "
            f"Most common: {pricing_landscape.get('most_common_tier', 'Unknown')}. "
            + ("Free tier available in market." if pricing_landscape.get("free_tier_available") else "No free tier found in market — opportunity.")
        )
    else:
        pricing_rationale = f"Competitive range: {pricing_range}. Based on competitor analysis of {len(report.competitors)} competitors."
    
    return FinancialModel(
        executive_summary=f"Based on research, a pricing range of {pricing_range} is recommended.",
        pricing_tiers=tiers,
        pricing_rationale=pricing_rationale,
        unit_economics={"cac": 50, "ltv": 1500, "ltv_cac_ratio": 30, "gross_margin_pct": 80, "monthly_churn_pct": 5},
        cost_breakdown=[
            {"category": "Hosting (VPS)", "monthly": 50, "annual": 600, "notes": "2 x $25 VPS"},
            {"category": "Domain & DNS", "monthly": 2, "annual": 24, "notes": "Domain + Cloudflare"},
            {"category": "Email service", "monthly": 15, "annual": 180, "notes": "Transactional + marketing"},
            {"category": "API costs (LLM)", "monthly": 100, "annual": 1200, "notes": "Variable, scales with usage"},
            {"category": "Developer (self)", "monthly": 0, "annual": 0, "notes": "Founder time, no cash salary"},
        ],
        revenue_projection=[
            {"month": 1, "users": 10, "mrr": 290, "expenses": 167, "profit": 123},
            {"month": 3, "users": 50, "mrr": 1450, "expenses": 167, "profit": 1283},
            {"month": 6, "users": 150, "mrr": 4350, "expenses": 200, "profit": 4150},
            {"month": 12, "users": 500, "mrr": 14500, "expenses": 300, "profit": 14200},
        ],
        break_even_month=1,
        break_even_users=2,
        funding_requirements=None,
        key_assumptions=[
            f"Based on {len(report.competitors)} competitors in space",
            "Conservative 5% monthly churn",
            "Bootstrapped (no external funding)",
            "Marketing through organic + community",
        ],
    )


async def generate_financial(report: ResearchReport) -> FinancialModel:
    """Generate financial model using DeepSeek Pro."""
    try:
        competitors_text = "\n".join(
            f"- {c.name}: model={c.business_model or 'Unknown'}, funding={c.funding or 'Unknown'}, market={c.target_market or 'Unknown'}"
            for c in report.competitors[:5]
        )
        market_text = ""
        ms = report.market_sizing
        if ms.tam:
            market_text += f"TAM: {ms.tam} (source: {ms.tam_source or 'Unknown'})\n"
        if ms.sam:
            market_text += f"SAM: {ms.sam} (source: {ms.sam_source or 'Unknown'})\n"
        if ms.growth_rate:
            market_text += f"Growth: {ms.growth_rate} (source: {ms.growth_source or 'Unknown'})\n"

        mv = report.market_validation
        community_text = f"Reddit: {mv.reddit_posts_found} posts, HN: {mv.hn_mentions} mentions, GH: {mv.gh_similar_projects} projects"

        prompt = f"""You are a startup financial analyst. Generate a detailed Financial Model for the following product.

PRODUCT: {report.idea}
PRICING RANGE (research suggestion): {report.recommended_pricing_range or "Not specified"}

=== RESEARCH CONTEXT ===

COMPETITOR FINANCIALS:
{competitors_text or "No competitor data"}

MARKET SIZING:
{market_text or "No market sizing data"}

COMMUNITY SIGNALS:
{community_text}

=== TASK ===

Produce a structured JSON with EXACTLY this shape (ONLY JSON, no markdown):

{{{{
  "executive_summary": "2-3 sentence financial outlook",
  "pricing_tiers": [
    {{{{
      "name": "Tier name",
      "price_monthly": 29.0,
      "price_yearly": 290.0,
      "description": "Who this is for",
      "features": ["Feature 1", "Feature 2"],
      "target": "indie/team/enterprise"
    }}}}
  ],
  "pricing_rationale": "Explain why these prices — reference competitors and value",
  "unit_economics": {{{{
    "cac": 50,
    "ltv": 1500,
    "ltv_cac_ratio": 30,
    "gross_margin_pct": 80,
    "monthly_churn_pct": 5,
    "payback_period_months": 3,
    "notes": "Key assumptions behind these numbers"
  }}}},
  "cost_breakdown": [
    {{{{"category": "Category name", "monthly": 50.0, "annual": 600.0, "notes": "Details"}}}}
  ],
  "revenue_projection": [
    {{{{"month": 1, "users": 10, "mrr": 290.0, "arr": 3480.0, "expenses": 1000.0, "profit": -710.0, "cumulative_profit": -710.0}}}}
  ],
  "break_even_month": 6,
  "break_even_users": 100,
  "funding_requirements": {{{{
    "total": 0,
    "runway_months": 12,
    "use_of_funds": {{{{"development": "100%", "marketing": "0%", "ops": "0%"}}}},
    "notes": "If bootstrapped, set total=0"
  }}}},
  "sensitivity_analysis": [
    {{{{"scenario": "High churn (10%/mo)", "assumption": "Churn doubles", "impact": "LTV drops to $750, break-even pushed to month 10", "mitigation": "Improve onboarding"}}}}
  ],
  "key_assumptions": [
    "Assumption 1 with justification"
  ]
}}}}

Rules:
- BE REALISTIC. Early stage startups have high churn and slow growth.
- If competitor data shows specific pricing models, reflect that.
- For bootstrapped: funding_requirements.total = 0.
- Revenue projections should be conservative (5-10% MoM growth for early stage).
- Include at LEAST months 1, 3, 6, 12 in revenue_projection.
- OUTPUT ONLY THE JSON OBJECT."""

        result = await llm.json_pro(prompt, temperature=0.2, max_tokens=4096, timeout=180)
        d = result
        if d:
            return FinancialModel(**d)

        logger.warning("Failed to parse Financial JSON, using deterministic")
        return _deterministic_financial(report)

    except Exception as e:
        logger.warning(f"Financial LLM failed: {e}, using deterministic fallback")
        return _deterministic_financial(report)
