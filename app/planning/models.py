"""Planning data models — Pydantic schemas for PRD, Functional, Financial, Technical specs."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ─── Pricing Tier ──────────────────────────────────────

class PricingTier(BaseModel):
    name: str
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    description: str
    features: list[str] = Field(default_factory=list)
    target: str  # "indie" / "team" / "enterprise"


# ─── Feature Anchor ───────────────────────────────────

class FeatureAnchor(BaseModel):
    """Feature with traceable anchor [F1], [F2], ... for Spec-Driven Development.
    
    TASK-068 — Each feature in the PRD receives a unique anchor that
    flows through the entire pipeline: PRD → Functional → CodeGen → Review.
    """
    anchor: str  # "F1", "F2", ...
    name: str
    description: str
    priority: str = "P0"  # P0/P1/P2
    acceptance_criteria: list[str] = Field(default_factory=list)
    effort: str = "medium"  # low/medium/high


# ─── PRD Spec ──────────────────────────────────────────

class PRDSpec(BaseModel):
    """Product Requirements Document."""
    product_name: str = ""
    tagline: str = ""
    problem_statement: str = ""
    target_audience: list[dict] = Field(default_factory=list)  # [{"segment": "...", "pain": "...", "size": "..."}]
    proposed_solution: str = ""
    user_stories: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)  # KPIs
    risks: list[dict] = Field(default_factory=list)  # [{"risk": "...", "impact": "high/med/low", "mitigation": "..."}]
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    validation_criteria: list[str] = Field(default_factory=list)  # How to validate this works
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    # TASK-062 — Traceability from Research → Planning
    derived_from_competitors: list[str] = Field(default_factory=list)  # Competitor names that informed features
    table_stakes_features: list[str] = Field(default_factory=list)  # Features ALL competitors have
    differentiator_features: list[str] = Field(default_factory=list)  # Features NO competitor has well
    pain_point_features: list[dict] = Field(default_factory=list)  # [{"pain":"...","feature":"...","competitor":"..."}]
    # TASK-068 — Spec-Driven Development: feature anchors for traceability
    features: list[FeatureAnchor] = Field(default_factory=list)  # Features with [Fn] anchors


# ─── Functional Spec ───────────────────────────────────

class FunctionalSpec(BaseModel):
    """Functional specification — features, flows, UX."""
    user_personas: list[dict] = Field(default_factory=list)  # [{"name": "...", "role": "...", "goals": [...], "pain_points": [...]}]
    core_features: list[dict] = Field(default_factory=list)  # [{"id": "F1", "name": "...", "description": "...", "priority": "P0/P1/P2", "acceptance_criteria": [...], "effort": "low/med/high"}]
    user_journeys: list[dict] = Field(default_factory=list)  # [{"scenario": "...", "steps": [...]}]
    non_functional_reqs: list[dict] = Field(default_factory=list)  # [{"category": "performance", "requirement": "..."}]
    integration_points: list[str] = Field(default_factory=list)
    data_privacy_notes: list[str] = Field(default_factory=list)
    ui_principles: list[str] = Field(default_factory=list)
    feature_roadmap: list[dict] = Field(default_factory=list)  # [{"phase": "MVP", "features": [...], "estimate": "2 weeks"}]
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Financial Model ───────────────────────────────────

class FinancialModel(BaseModel):
    """Financial projections and unit economics."""
    executive_summary: str = ""
    pricing_tiers: list[PricingTier] = Field(default_factory=list)
    pricing_rationale: str = ""
    unit_economics: dict = Field(default_factory=dict)  # {"cac": ..., "ltv": ..., "margin": ...}
    cost_breakdown: list[dict] = Field(default_factory=list)  # [{"category": "hosting", "monthly": 50, "annual": 600, "notes": "..."}]
    revenue_projection: list[dict] = Field(default_factory=list)  # [{"month": 1, "users": 10, "mrr": 290, "expenses": 2000, "profit": -1710}]
    break_even_month: Optional[int] = None
    break_even_users: Optional[int] = None
    funding_requirements: Optional[dict] = None  # {"total": ..., "use_of_funds": {...}}
    sensitivity_analysis: list[dict] = Field(default_factory=list)  # [{"scenario": "...", "assumption": "...", "impact": "..."}]
    key_assumptions: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Technical Spec ────────────────────────────────────

class TechnicalSpec(BaseModel):
    """Technical architecture and implementation plan."""
    stack_recommendation: str = ""
    stack_table: list[dict] = Field(default_factory=list)  # [{"layer": "frontend", "technology": "React/Vite", "rationale": "..."}]
    architecture_notes: str = ""
    data_model: list[dict] = Field(default_factory=list)  # [{"entity": "User", "fields": [...], "relations": [...]}]
    api_endpoints: list[dict] = Field(default_factory=list)  # [{"method": "GET", "path": "/users", "description": "...", "auth": "..."}]
    deployment_architecture: str = ""
    scalability_notes: str = ""
    security_requirements: list[str] = Field(default_factory=list)
    third_party_deps: list[str] = Field(default_factory=list)
    development_phases: list[dict] = Field(default_factory=list)  # [{"phase": "Sprint 1", "tasks": [...], "duration": "1 week"}]
    estimated_effort: Optional[str] = None
    estimated_infra_cost_monthly: Optional[float] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Full Planning Output ──────────────────────────────

class PlanningOutput(BaseModel):
    """Top-level planning output — all 4 specs + extra documents."""
    idea: str
    research_summary: str = ""
    prd: PRDSpec = Field(default_factory=PRDSpec)
    functional: FunctionalSpec = Field(default_factory=FunctionalSpec)
    financial: FinancialModel = Field(default_factory=FinancialModel)
    technical: TechnicalSpec = Field(default_factory=TechnicalSpec)
    extra_docs: dict = Field(default_factory=dict)  # TASK-065 — {doc_id: {...generated json...}}
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generation_duration_ms: int = 0
