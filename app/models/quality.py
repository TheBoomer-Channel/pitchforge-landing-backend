"""AI Quality Monitoring models — TASK-059.

EvalCase: A single golden evaluation case (input + expected + rubric).
EvalResult: The result of running an eval case against the LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from beanie import Document
from pydantic import Field


class EvalResult(Document):
    """Result of a single AI quality eval case execution.

    Stores the case input, expected output, actual output, and score.
    Used for regression detection and quality trending.
    """

    case_id: str  # Unique ID for the eval case (e.g. "landing-001")
    category: str = "general"  # landing, pitch, pricing, planning, research, code
    prompt: str  # The input prompt used
    expected_output: str  # The expected/ideal output
    actual_output: str  # What the LLM actually produced
    score: float = 0.0  # 0.0 to 1.0 — LLM-as-judge score
    rubric: str = ""  # Scoring rubric used
    model: str = "deepseek-chat"  # Model that was evaluated
    task_type: str = "chat"  # Task type used for routing
    latency_ms: float = 0.0
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str = ""  # Batch run ID (for grouping nightly runs)
    error: Optional[str] = None  # Error message if execution failed

    class Settings:
        name = "quality_evals"
        indexes = [
            [("ts", -1)],
            [("run_id", 1)],
            [("case_id", 1), ("ts", -1)],
            [("category", 1), ("ts", -1)],
            [("score", 1)],
            [("model", 1), ("ts", -1)],
        ]
