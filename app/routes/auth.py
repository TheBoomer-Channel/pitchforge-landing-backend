"""Auth routes — Clerk-managed authentication.

Registration and login are handled entirely by Clerk (frontend SDK).
Backend only needs /auth/me to return the synced user profile.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user, get_or_create_user
from ..database import User, Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class UserInfoResponse(BaseModel):
    id: str
    email: str
    name: str
    tier: str
    projects_count: int
    created_at: str


@router.get("/me", response_model=UserInfoResponse)
async def get_profile(
    user: User = Depends(get_current_user),
):
    """Get the authenticated user's profile with projects count."""
    projects = await Project.find(Project.user_id == user.clerk_user_id).to_list()
    projects_count = len(projects)

    return UserInfoResponse(
        id=user.clerk_user_id,
        email=user.email or "",
        name=user.name or "",
        tier=user.tier,
        projects_count=projects_count,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )


@router.post("/sync")
async def sync_user(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Sync Clerk user data to our database.

    Called by the frontend after Clerk authentication to ensure
    the user exists in MongoDB with their Clerk profile.
    """
    body = await request.json()
    email = body.get("email", user.email or "")
    name = body.get("name", user.name or "")

    if email or name:
        user.email = email
        user.name = name
        await user.save()

    return {
        "id": user.clerk_user_id,
        "email": user.email,
        "name": user.name,
        "tier": user.tier,
    }
