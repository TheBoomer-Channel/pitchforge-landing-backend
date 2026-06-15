"""Token & Pause/Resume API routes — Clerk + MongoDB edition."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import User
from ..services.token_service import (
    TokenService, pause_job, resume_job, list_paused_jobs,
    TOKEN_COST_PER_TASK,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tokens", tags=["tokens"])


class TokenStatusResponse(BaseModel):
    balance: int
    tier_limit: int
    tier: str
    tasks_remaining: int
    is_paused: bool
    paused_jobs: list[str]

class ConsumeRequest(BaseModel):
    project_id: str
    task_id: str
    tokens: int = TOKEN_COST_PER_TASK
    description: str = ""

class ConsumeResponse(BaseModel):
    can_proceed: bool
    reason: str
    tokens_consumed: int
    remaining_balance: int
    paused: bool

class PauseResponse(BaseModel):
    paused: bool
    reason: str
    jobs: list[str]


@router.get("/status", response_model=TokenStatusResponse)
async def token_status(user: User = Depends(get_current_user)):
    balance = await TokenService.get_token_balance(user.clerk_user_id)
    tier_limit = await TokenService.get_tier_limit(user.tier)
    paused_data = list_paused_jobs()
    my_paused = [k for k in paused_data.keys()]
    return TokenStatusResponse(balance=balance, tier_limit=tier_limit, tier=user.tier, tasks_remaining=balance // TOKEN_COST_PER_TASK, is_paused=len(my_paused) > 0, paused_jobs=my_paused)


@router.post("/consume", response_model=ConsumeResponse)
async def consume_tokens(body: ConsumeRequest, user: User = Depends(get_current_user)):
    result = await TokenService.check_and_consume(user_id=user.clerk_user_id, project_id=body.project_id, task_id=body.task_id, cost=body.tokens, description=body.description)
    return ConsumeResponse(**result)


@router.post("/pause/{project_id}", response_model=PauseResponse)
async def pause_execution(project_id: str, reason: str = Query("Manually paused by user"), user: User = Depends(get_current_user)):
    pause_job(project_id, reason)
    return PauseResponse(paused=True, reason=reason, jobs=list(list_paused_jobs().keys()))


@router.post("/resume/{project_id}", response_model=PauseResponse)
async def resume_execution(project_id: str, user: User = Depends(get_current_user)):
    was_paused = resume_job(project_id)
    return PauseResponse(paused=not was_paused, reason="Resumed" if was_paused else "Was not paused", jobs=list(list_paused_jobs().keys()))


@router.get("/paused")
async def list_paused(user: User = Depends(get_current_user)):
    all_paused = list_paused_jobs()
    return {"paused": all_paused, "total": len(all_paused)}


@router.get("/usage")
async def token_usage_history(limit: int = Query(20, ge=1, le=100), user: User = Depends(get_current_user)):
    history = await TokenService.get_usage_history(user.clerk_user_id, limit)
    return {"usage": history, "total": len(history)}
