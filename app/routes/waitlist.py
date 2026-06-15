"""Waitlist Routes — landing page email subscription via ListMonk."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.waitlist import subscribe

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/waitlist", tags=["waitlist"])


class SubscribeRequest(BaseModel):
    email: str
    name: Optional[str] = ""
    api_user: Optional[str] = ""
    api_token: Optional[str] = ""
    list_id: Optional[int] = 0


class SubscribeResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None


@router.post("/subscribe", response_model=SubscribeResponse)
async def api_subscribe(req: SubscribeRequest):
    """Subscribe an email to the waitlist via ListMonk."""
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="Valid email required")

    result = await subscribe(
        email=req.email,
        name=req.name,
        api_user=req.api_user,
        api_token=req.api_token,
        list_id=req.list_id,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Subscription failed"))

    return SubscribeResponse(
        success=True,
        message=result.get("message", "Subscribed!"),
        data=result.get("data"),
    )


@router.get("/health")
async def api_health():
    """Check waitlist service health."""
    return {"status": "ok", "service": "listmonk", "url": "https://newsletter.transcend.cargoffer.com"}
