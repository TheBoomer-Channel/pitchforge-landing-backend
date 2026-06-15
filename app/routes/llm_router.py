"""LLM Router API routes — TASK-056.

Endpoints:
  - GET /api/v1/llm/status — Current LLMRouter status (models, circuit breakers)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..database import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/llm", tags=["llm", "monitoring"])


@router.get("/status", summary="LLM Router status — models, circuit breakers, routing")
async def get_llm_router_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns the current LLM Router status including:
    - Available models and their providers
    - Circuit breaker states (open/closed)
    - Total calls and failures per model
    - Average latency per model
    - Task routing configuration
    """
    from ..services.llm_router import get_router
    router = get_router()
    return router.get_status()
