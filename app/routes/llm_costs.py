"""LLM Cost Monitoring routes — TASK-026.

Endpoints:
  - GET  /api/v1/llm-costs/today       — Today's cost summary
  - GET  /api/v1/llm-costs/monthly     — Monthly cost summary (with per-day breakdown)
  - POST /api/v1/llm-costs/check-alert — Manual budget check (gated by cron secret)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user
from ..database import User
from ..services.llm_cost_tracker import cost_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/llm-costs", tags=["billing", "monitoring"])

CRON_SECRET = os.getenv("TRIAL_CRON_SECRET", "dev-cron-secret-change-in-prod")


@router.get("/today", summary="Today's LLM cost summary")
async def get_today_costs(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns today's LLM cost summary: total USD, tokens, calls,
    broken down by provider, model, and top users."""
    summary = await cost_tracker.get_daily_summary()
    return summary


@router.get("/monthly", summary="Monthly LLM cost summary with daily breakdown")
async def get_monthly_costs(
    user: User = Depends(get_current_user),
    month: str = "",
) -> dict:
    """Returns monthly LLM cost summary with per-day breakdown.

    Args:
        month: Optional "YYYY-MM" format. Defaults to current month.
    """
    ym = month.strip() if month else None
    summary = await cost_tracker.get_monthly_summary(ym)
    return summary


@router.post("/check-alert", summary="Manually trigger budget alert check (cron)")
async def check_llm_budget_alert(request: Request) -> dict:
    """Check if any LLM cost budget thresholds are exceeded and send
    Slack alert if so.

    Gated by X-Cron-Secret header (same as TASK-018 trial cron).
    """
    provided = request.headers.get("X-Cron-Secret", "")
    if provided != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    today = datetime.now(timezone.utc)
    alert = await cost_tracker.check_budget_alert(today)

    return {
        "date": today.strftime("%Y-%m-%d"),
        "alert_triggered": alert is not None,
        "alert_message": alert,
        "checked_at": today.isoformat(),
    }
