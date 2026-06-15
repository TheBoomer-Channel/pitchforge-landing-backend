"""Research data models — Pydantic schemas for all research output."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ─── Source Types ───────────────────────────────────────

class SourceType(str):
    """Standardized source type identifiers.
    
    Add new entries here when creating a new source module.
    """
    TAVILY = "tavily"
    REDDIT = "reddit"
    HACKER_NEWS = "hacker_news"
    GITHUB = "github"
    WIKIPEDIA = "wikipedia"
    WEB = "web_extract"


# ─── Source Results ─────────────────────────────────────

class BaseSourceResult(BaseModel):
    """Every source returns this shape."""
    source: str
    success: bool
    error: Optional[str] = None
    data: list[dict] = Field(default_factory=list)
    raw_metadata: dict = Field(default_factory=dict)


# ─── Competitor ─────────────────────────────────────────

class Competitor(BaseModel):
    name: str
    description: str
    website: Optional[str] = None
    funding: Optional[str] = None
    funding_source: Optional[str] = None
    business_model: Optional[str] = None
    target_market: Optional[str] = None
    pricing: Optional[str] = None
    pain_points: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    source: str = "unknown"
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.5  # 0.0-1.0 how reliable the data is
    # TASK-064 — Structured pricing, pain points with sources, feature checklist
    pricing_tiers: list[dict] = Field(default_factory=list)  # [{"name":"Free","price":0,"billing":"monthly"}]
    pricing_source: Optional[str] = None
    pricing_verified: bool = False
    pain_points_with_sources: list[dict] = Field(default_factory=list)  # [{"pain":"...","source":"reddit","severity":"high","url":"..."}]
    features_detected: list[str] = Field(default_factory=list)  # Features confirmed from this competitor


# ─── Market Validation ──────────────────────────────────

class MarketValidation(BaseModel):
    """Signals from communities about demand/pain."""
    reddit_posts_found: int = 0
    reddit_sentiment: Optional[str] = None  # positive/negative/mixed
    reddit_top_posts: list = Field(default_factory=list)
    hn_mentions: int = 0
    hn_top_posts: list = Field(default_factory=list)  # list of dicts OR strings
    gh_similar_projects: int = 0
    gh_projects: list = Field(default_factory=list)  # list of dicts OR strings
    common_complaints: list[str] = Field(default_factory=list)
    common_desires: list[str] = Field(default_factory=list)
    overall_sentiment: Optional[str] = None


# ─── Market Sizing ──────────────────────────────────────

class MarketSizing(BaseModel):
    tam: Optional[str] = None
    tam_source: Optional[str] = None
    tam_confidence: float = 0.0
    sam: Optional[str] = None
    sam_source: Optional[str] = None
    sam_confidence: float = 0.0
    growth_rate: Optional[str] = None
    growth_source: Optional[str] = None
    key_trends: list[str] = Field(default_factory=list)


# ─── Opportunity Gap ────────────────────────────────────

class OpportunityGap(BaseModel):
    gap: str
    evidence: list[str] = Field(default_factory=list)
    severity: str = "medium"  # low / medium / high
    source: str = "unknown"


# ─── Full Report ────────────────────────────────────────

class ResearchReport(BaseModel):
    """Top-level research output."""
    idea: str
    summary: str = ""
    
    competitors: list[Competitor] = Field(default_factory=list)
    market_validation: MarketValidation = Field(default_factory=MarketValidation)
    market_sizing: MarketSizing = Field(default_factory=MarketSizing)
    opportunity_gaps: list[OpportunityGap] = Field(default_factory=list)
    
    recommended_mvp_features: list[str] = Field(default_factory=list)
    recommended_pricing_range: Optional[str] = None
    recommended_positioning: Optional[str] = None
    risk_factors: list[str] = Field(default_factory=list)
    
    # TASK-064 — Competitive analysis insights from CompetitorAnalyzer
    competitive_insights: Optional[dict] = None  # {table_stakes, differentiation_gaps, pain_summary, pricing_landscape, must_have_features}
    
    sources_used: list[str] = Field(default_factory=list)
    source_quality: dict[str, float] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    research_duration_ms: int = 0
    
    # Raw source data (for debugging / refinement)
    raw_sources: dict[str, BaseSourceResult] = Field(default_factory=dict, exclude=True)


# ─── API Schemas ────────────────────────────────────────

class ResearchRequest(BaseModel):
    project_id: str
    idea_description: str
    target_market: Optional[str] = None
    business_model: Optional[str] = None


class ResearchProgress(BaseModel):
    """WebSocket progress update."""
    project_id: str
    status: str  # started / searching / analyzing / synthesizing / done / error
    progress_pct: float = 0.0
    message: str = ""
    current_source: Optional[str] = None
    sources_done: list[str] = Field(default_factory=list)
    sources_total: int = 0
