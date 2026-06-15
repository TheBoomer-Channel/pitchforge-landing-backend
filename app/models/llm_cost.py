"""LLM cost tracking model — TASK-026.

Tracks every LLM API call with token counts and calculated USD cost.
Enables daily cost aggregation, per-user budgets, and budget alerts.

Schema:
  (id, user_id, provider, model, prompt_tokens, completion_tokens,
   cost_usd, ts, metadata)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


class LLMCost(Document):
    """A single LLM API call cost record.

    Written on every successful LLM completion. Used for:
    - Daily cost aggregation (per-provider, per-model)
    - Per-user budget enforcement
    - Budget alerts (Slack webhook)
    - Dashboard cost visualization
    """

    user_id: Optional[str] = None  # Clerk user ID (None = internal/system)
    project_id: Optional[str] = None  # Optional project context
    provider: str = "deepseek"  # deepseek, openai, anthropic, etc.
    model: str = "deepseek-chat"  # e.g. deepseek-chat, deepseek-reasoner, gpt-4o
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0  # Calculated from token counts + per-model pricing
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)  # source, task type, request_id, etc.
    request_id: Optional[str] = None  # Cross-ref to request log / OTel trace

    class Settings:
        name = "llm_costs"
        indexes = [
            [("ts", -1)],
            [("ts", -1), ("provider", 1)],
            [("ts", -1), ("model", 1)],
            [("user_id", 1), ("ts", -1)],
            [("user_id", 1), ("ts", -1), ("provider", 1)],
            [("project_id", 1), ("ts", -1)],
            # For daily aggregation queries
            [("provider", 1), ("model", 1), ("ts", -1)],
        ]
