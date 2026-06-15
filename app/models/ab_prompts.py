"""AB Prompt Testing — MongoDB models for prompt experimentation framework.

TASK-058 — A/B Prompt Testing.
Each prompt has variants with traffic percentage allocation.
Assignment is deterministic by user_id hash.
Quality scoring via LLM-as-judge with rubric evaluation.
"""

from datetime import datetime, timezone
from typing import Optional
from beanie import Document, Indexed
from pydantic import BaseModel, Field


class PromptVariant(BaseModel):
    """A single variant of a prompt."""
    key: str  # "control", "v1", "v2", etc.
    name: str  # Human-readable name (e.g. "Control (original)", "V1 - Concise")
    content: str  # The actual prompt text
    traffic_pct: int = Field(ge=0, le=100, default=50)  # % of traffic assigned
    is_control: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QualityScore(BaseModel):
    """A quality score from LLM-as-judge evaluation."""
    overall: float = 0.0  # 0-10
    relevance: float = 0.0
    accuracy: float = 0.0
    clarity: float = 0.0
    completeness: float = 0.0
    reasoning: Optional[str] = None  # Judge's reasoning


class PromptLogEntry(BaseModel):
    """A single prompt execution log."""
    log_id: str  # Unique ID for this execution
    user_id: str
    prompt_name: str
    variant_key: str
    input_snippet: str  # First 200 chars of user input
    output_snippet: str  # First 500 chars of output
    latency_ms: float
    token_count: int
    user_rating: Optional[int] = None  # Thumbs up/down: 1 or 0
    quality_score: Optional[QualityScore] = None
    task_type: str = "chat"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PromptExperiment(Document):
    """Top-level document — one per named prompt experiment."""
    name: str  # e.g. "research_synthesis_prompt", "pitch_generator_prompt"
    description: str = ""
    enabled: bool = True
    variants: list[PromptVariant] = Field(default_factory=list)
    logs: list[PromptLogEntry] = Field(default_factory=list)  # Capped at ~1000, older archived
    total_calls: int = 0
    total_user_ratings: int = 0
    total_quality_scores: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ab_prompt_experiments"
        indexes = [
            [("name", 1)],
            [("enabled", 1)],
        ]


# ── Schemas ────────────────────────────────────────────

class CreateExperimentRequest(BaseModel):
    name: str
    description: str = ""
    control_prompt: str
    variants: list[dict] = Field(default_factory=list)  # [{content, name, traffic_pct}]


class AddVariantRequest(BaseModel):
    name: str
    content: str
    traffic_pct: int = 0


class UpdateTrafficRequest(BaseModel):
    variant_key: str
    traffic_pct: int


class LogExecutionRequest(BaseModel):
    prompt_name: str
    variant_key: str
    user_id: str
    input_text: str
    output_text: str
    latency_ms: float
    token_count: int
    task_type: str = "chat"


class RateOutputRequest(BaseModel):
    log_id: str
    rating: int  # 0 or 1


class QualityScoreRequest(BaseModel):
    log_id: str


class AssignVariantResponse(BaseModel):
    prompt_name: str
    variant_key: str
    variant_content: str
    is_control: bool
    traffic_pct: int


class VariantStats(BaseModel):
    variant_key: str
    name: str
    traffic_pct: int
    total_calls: int
    total_ratings: int
    positive_ratings: int
    avg_quality_score: float
    avg_latency_ms: float
    is_control: bool


class ExperimentStatusResponse(BaseModel):
    name: str
    enabled: bool
    description: str
    variants: list[VariantStats]
    total_calls: int
    total_ratings: int
    winner: Optional[str] = None
    confidence: Optional[float] = None


class QualityScoreResponse(BaseModel):
    score: float
    relevance: float
    accuracy: float
    clarity: float
    completeness: float
    reasoning: str
