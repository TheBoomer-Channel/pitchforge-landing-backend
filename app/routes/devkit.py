"""DevKit routes — Active Learning briefings, pattern detection, and agent status.

TASK-069 — Proactive session briefings with patterns, tips, and trends.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..devkit import DevAgent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/devkit", tags=["devkit"])

# Default project directory — configurable via env
_DEFAULT_PROJECT = str(Path(__file__).parent.parent.parent)

_agent: DevAgent | None = None


def _get_agent() -> DevAgent:
    """Get or create the DevAgent singleton."""
    global _agent
    if _agent is None:
        _agent = DevAgent(_DEFAULT_PROJECT)
    return _agent


@router.get("/briefing")
async def get_briefing():
    """Get a session briefing with detected patterns, tips, and trends.

    Scans the vault's learnings.md and generates a briefing with:
    - Recent lessons and their count
    - Recurring patterns (≥3 occurrences)
    - Actionable tips
    - Error trend (improving/stable/degrading)
    """
    agent = _get_agent()
    try:
        briefing = agent.get_briefing()
        return briefing
    except Exception as e:
        logger.error(f"Failed to generate briefing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate briefing")


@router.get("/status")
async def get_devkit_status():
    """Get full DevKit status including vault, tasks, and briefing."""
    agent = _get_agent()
    try:
        status = agent.status()
        return status
    except Exception as e:
        logger.error(f"Failed to get DevKit status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get status")


@router.post("/setup")
async def setup_devkit():
    """Initialize the DevKit vault and task system."""
    agent = _get_agent()
    try:
        result = agent.setup()
        return {"status": "ok", "detail": result}
    except Exception as e:
        logger.error(f"Failed to setup DevKit: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to setup DevKit")
