"""Token Service — token-based billing for code generation with pause/resume.

Uses MongoDB TokenUsage document and TierLimits from Stripe metadata.
"""

import logging
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from .tier_limits import TierLimits

logger = logging.getLogger(__name__)

TOKEN_COST_PER_TASK = 500
TOKEN_COST_PER_CYCLE = 200
TOKEN_WARNING_THRESHOLD = 500
TOKEN_CRITICAL_THRESHOLD = 100

_paused_jobs: dict[str, str] = {}


def pause_job(job_id: str, reason: str = "Out of tokens") -> None:
    _paused_jobs[job_id] = reason
    logger.info(f"Job {job_id} paused: {reason}")

def resume_job(job_id: str) -> bool:
    return _paused_jobs.pop(job_id, None) is not None

def is_job_paused(job_id: str) -> bool:
    return job_id in _paused_jobs

def get_paused_reason(job_id: str) -> Optional[str]:
    return _paused_jobs.get(job_id)

def list_paused_jobs() -> dict[str, str]:
    return dict(_paused_jobs)


class TokenService:
    """Manages token balance and consumption for code generation."""

    @staticmethod
    async def get_tier_limit(tier: str) -> int:
        limits = TierLimits.get_tier_limits(tier)
        return limits.get("max_tokens", 2000)

    @staticmethod
    async def get_token_balance(user_id: str) -> int:
        from ..database import User, TokenUsage
        user = await User.find_one(User.clerk_user_id == user_id)
        if not user:
            return 0
        base = await TokenService.get_tier_limit(user.tier)
        usage = await TokenUsage.find(TokenUsage.user_id == user_id).to_list()
        total_consumed = sum(r.tokens_consumed for r in usage)
        return max(0, base - total_consumed)

    @staticmethod
    async def consume_tokens(user_id: str, project_id: str, task_id: str, tokens: int, description: str = "") -> dict:
        from ..database import TokenUsage
        usage = TokenUsage(
            id=str(uuid4()),
            user_id=user_id,
            project_id=project_id,
            task_id=task_id,
            tokens_consumed=tokens,
            description=description or f"Task {task_id}",
        )
        await usage.insert()
        balance = await TokenService.get_token_balance(user_id)
        logger.info(f"Tokens consumed: {tokens} for {task_id}. Balance: {balance}")
        return {
            "tokens_consumed": tokens,
            "remaining_balance": balance,
            "needs_top_up": balance < TOKEN_CRITICAL_THRESHOLD,
            "needs_warning": balance < TOKEN_WARNING_THRESHOLD,
        }

    @staticmethod
    async def check_and_consume(user_id: str, project_id: str, task_id: str, cost: int = TOKEN_COST_PER_TASK, description: str = "") -> dict:
        balance = await TokenService.get_token_balance(user_id)
        if balance < cost:
            pause_job(project_id, f"Insufficient tokens. Need {cost}, have {balance}")
            return {"can_proceed": False, "reason": f"Insufficient tokens. Need {cost}, have {balance}", "tokens_consumed": 0, "remaining_balance": balance, "paused": True}
        result = await TokenService.consume_tokens(user_id=user_id, project_id=project_id, task_id=task_id, tokens=cost, description=description)
        result["can_proceed"] = not result["needs_top_up"]
        result["paused"] = result["needs_top_up"]
        if result["needs_top_up"]:
            pause_job(project_id, "Token balance critically low. Purchase more to continue.")
        return result

    @staticmethod
    async def purchase_tokens(user_id: str, amount: Decimal, stripe_session_id: str) -> dict:
        from ..database import TokenPurchase
        tokens_added = int(amount * 1000)
        purchase = TokenPurchase(id=str(uuid4()), user_id=user_id, amount=amount, tokens_added=tokens_added, stripe_session_id=stripe_session_id)
        await purchase.insert()
        logger.info(f"Tokens purchased: {tokens_added} for user {user_id}")
        return {"tokens_added": tokens_added, "amount": str(amount), "new_balance": await TokenService.get_token_balance(user_id)}

    @staticmethod
    async def get_usage_history(user_id: str, limit: int = 20) -> list[dict]:
        from ..database import TokenUsage
        records = await TokenUsage.find(TokenUsage.user_id == user_id).sort(-TokenUsage.created_at).limit(limit).to_list()
        return [{"id": r.id, "project_id": r.project_id, "task_id": r.task_id, "tokens_consumed": r.tokens_consumed, "description": r.description, "created_at": r.created_at.isoformat() if r.created_at else None} for r in records]
