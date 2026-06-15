"""Usage-based billing models — TASK-019.

Captures consumable metrics for each user so we can:
  * Enforce tier limits (soft cap → warning, hard cap → block)
  * Report current-month aggregates to the user (UI chart)
  * Push metered usage to Stripe for overage invoicing

Metrics tracked:
  - research_call: per research run (count)
  - llm_token_in: tokens sent to LLM providers
  - llm_token_out: tokens received from LLM providers
  - pdf_export: per PDF generation (count)
  - api_call: per authenticated API call (rate-limited separately)

Monthly aggregation:
  Collection `usage_monthly_aggregates` — denormalised per (user_id, metric, month).
  Updated on every event via an upsert with $inc (atomic, lock-free).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


# Built-in list of known metrics (extensible)
METRICS = frozenset({
    "research_call",
    "llm_token_in",
    "llm_token_out",
    "pdf_export",
    "api_call",
})


class UsageEvent(Document):
    """An individual usage event. Written on every API call that consumes a
    metered resource. Used for real-time cap enforcement and auditing.

    After-the-fact aggregation is done into MonthlyUsage to avoid
    scanning millions of tiny events for every API call.
    """

    user_id: Indexed(str)
    metric: Indexed(str)  # one of METRICS
    quantity: float = 1.0  # tokens, count, etc.
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = Field(default_factory=dict)  # source, model, project_id, etc.
    request_id: Optional[str] = None  # cross-ref to audit log / request log

    class Settings:
        name = "usage_events"
        indexes = [
            "user_id",
            "metric",
            [("user_id", 1), ("ts", -1)],
            [("user_id", 1), ("metric", 1), ("ts", -1)],
            [("ts", -1)],
        ]


class MonthlyUsage(Document):
    """Denormalised monthly aggregate per (user_id, metric).

    Upserted on the critical path (lock-free via `$inc` / `$set`).
    """

    user_id: Indexed(str)
    metric: Indexed(str)
    month: str  # "2026-06"
    total: float = 0.0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_event_ts: Optional[datetime] = None

    class Settings:
        name = "usage_monthly_aggregates"
        indexes = [
            [("user_id", 1), ("month", 1)],
            [("user_id", 1), ("metric", 1), ("month", 1)],
            [("month", 1), ("user_id", 1)],
        ]
