"""AI Quality Monitoring routes — TASK-059.

Endpoints:
- GET  /internal/ai-quality          → latest quality report with trend
- GET  /internal/ai-quality/run/{id} → detailed results for a specific run
- POST /internal/ai-quality/run      → trigger a new eval run
- GET  /internal/ai-quality/cases    → get the number of available eval cases
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ..services.ai_quality import eval_runner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/ai-quality", tags=["quality"])


@router.get("")
async def get_quality_report():
    """Get latest AI quality report with trend data.

    Returns average scores, per-category breakdowns, per-model stats,
    and recent run history for trend detection.
    """
    try:
        report = await eval_runner.get_report(limit=10)
        return report
    except Exception as e:
        logger.error(f"Failed to get quality report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get quality report")


@router.get("/run/{run_id}")
async def get_run_detail(run_id: str):
    """Get detailed results for a specific eval run."""
    try:
        report = await eval_runner.get_run(run_id)
        if report.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get run {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get run results")


@router.post("/run")
async def trigger_eval_run():
    """Trigger a full AI quality eval suite run.

    Runs all golden cases through the LLM, scores results using
    LLM-as-judge, and checks for regressions.
    """
    try:
        report = await eval_runner.run_full_suite()
        return report
    except Exception as e:
        logger.error(f"Failed to run eval suite: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run eval suite")


@router.get("/cases")
async def get_case_count():
    """Get the number of available eval cases in the golden dataset."""
    try:
        count = eval_runner.get_case_count()
        return {"total_cases": count}
    except Exception as e:
        logger.error(f"Failed to get case count: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get case count")
