"""AB Copy — MongoDB model for A/B copy variant generation and tracking.

TASK-052 — A/B Copy Generator.
Each project can have copy sets (headline, subheadline, CTA, etc.).
Each set has a control (original) and up to 5 AI-generated variants.
Impressions and conversions are tracked per variant for winner selection.
"""

from datetime import datetime, timezone
from typing import Optional
from beanie import Document, Indexed
from pydantic import BaseModel, Field


class CopySet(BaseModel):
    """A logical copy slot within a project (e.g. headline, subheadline, cta)."""
    slot: str  # e.g. "headline", "subheadline", "cta_primary", "cta_secondary"
    control: str  # The original copy text
    variants: list[str] = Field(default_factory=list)  # AI-generated variants (up to 5)
    impressions: dict[str, int] = Field(default_factory=dict)  # variant_key → count
    conversions: dict[str, int] = Field(default_factory=dict)  # variant_key → count
    winner: Optional[str] = None  # variant_key of the statistically significant winner
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ABTestVariant(BaseModel):
    """Single variant in a response."""
    key: str
    text: str
    angle: str
    impressions: int = 0
    conversions: int = 0
    conversion_rate: float = 0.0
    is_winner: bool = False


class CopyVariant(Document):
    """Top-level document — one per project."""
    project_id: Indexed(str)
    user_id: str
    idea: str
    copy_sets: dict[str, CopySet] = Field(default_factory=dict)  # slot → CopySet
    total_impressions: int = 0
    total_conversions: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ab_copy_variants"
        indexes = [
            [("project_id", 1)],
            [("user_id", 1)],
        ]


# ── Schemas ────────────────────────────────────────────

class GenerateVariantsRequest(BaseModel):
    project_id: str
    slot: str  # headline, subheadline, cta_primary, cta_secondary
    text: str  # The current copy text to generate variants from
    idea: str  # For LLM context


class GenerateVariantsResponse(BaseModel):
    project_id: str
    slot: str
    control: str
    variants: list[ABTestVariant]
    winner: Optional[str] = None


class TrackImpressionRequest(BaseModel):
    project_id: str
    slot: str
    variant_key: str  # "control" or "v0", "v1", etc.


class TrackConversionRequest(BaseModel):
    project_id: str
    slot: str
    variant_key: str


class ABTestStatusResponse(BaseModel):
    project_id: str
    slot: str
    control: str
    variants: list[ABTestVariant]
    winner: Optional[str] = None
    total_impressions: int
    total_conversions: int


class ABTestSummaryResponse(BaseModel):
    project_id: str
    idea: str
    copy_sets: dict[str, ABTestStatusResponse]
    total_impressions: int
    total_conversions: int
