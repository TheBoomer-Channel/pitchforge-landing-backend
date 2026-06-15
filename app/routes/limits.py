"""Limits API route — returns tier usage and limits for the current user."""

import logging

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..database import User
from ..services.tier_limits import TierLimits

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/limits", tags=["limits"])


@router.get("/")
async def get_limits(
    user: User = Depends(get_current_user),
):
    """Get current tier limits and usage for the authenticated user."""
    summary = await TierLimits.get_tier_summary(user)
    return summary
