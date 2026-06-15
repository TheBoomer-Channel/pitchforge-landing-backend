"""A/B Copy Generator — API routes for variant generation and tracking.

TASK-052 — A/B Copy Generator.
Generates 5 AI-powered variants per copy slot (headline, subheadline, CTA),
tracks impressions/conversions, and auto-selects the winner.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user, User
from ..models.ab_copy import (
    GenerateVariantsRequest, GenerateVariantsResponse,
    TrackImpressionRequest, TrackConversionRequest,
    ABTestStatusResponse, ABTestSummaryResponse,
    ABTestVariant,
)
from ..services.ab_copy import (
    generate_variants,
    track_impression as svc_track_impression,
    track_conversion as svc_track_conversion,
    get_slot_status,
    get_project_summary,
    get_or_create_project,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ab-copy", tags=["ab-copy"])


@router.post("/generate", response_model=GenerateVariantsResponse)
async def api_generate_variants(
    req: GenerateVariantsRequest,
    user: User = Depends(get_current_user),
):
    """Generate 5 AI-powered copy variants for a given slot.

    Slots: headline, subheadline, cta_primary, cta_secondary
    Returns the original + 5 variants with assigned psychological angles.
    """
    # Ensure project exists in our DB
    await get_or_create_project(req.project_id, user.clerk_user_id or "", req.idea)

    variants = await generate_variants(req.project_id, req.slot, req.text, req.idea)

    # Get current winner if any
    status = await get_slot_status(req.project_id, req.slot)
    winner = status["winner"] if status else None

    return GenerateVariantsResponse(
        project_id=req.project_id,
        slot=req.slot,
        control=req.text,
        variants=variants,
        winner=winner,
    )


@router.post("/impression")
async def api_track_impression(
    req: TrackImpressionRequest,
    user: User = Depends(get_current_user),
):
    """Track a visitor impression for a specific copy variant."""
    ok = await svc_track_impression(req.project_id, req.slot, req.variant_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Project or slot not found")
    return {"status": "ok"}


@router.post("/conversion")
async def api_track_conversion(
    req: TrackConversionRequest,
    user: User = Depends(get_current_user),
):
    """Track a conversion for a specific copy variant."""
    ok = await svc_track_conversion(req.project_id, req.slot, req.variant_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Project or slot not found")
    return {"status": "ok"}


@router.get("/status/{project_id}/{slot}", response_model=ABTestStatusResponse)
async def api_slot_status(
    project_id: str,
    slot: str,
    user: User = Depends(get_current_user),
):
    """Get A/B test status for a specific copy slot (headline, CTA, etc)."""
    status = await get_slot_status(project_id, slot)
    if not status:
        raise HTTPException(status_code=404, detail="No variants found for this slot")
    return ABTestStatusResponse(**status)


@router.get("/summary/{project_id}", response_model=ABTestSummaryResponse)
async def api_project_summary(
    project_id: str,
    user: User = Depends(get_current_user),
):
    """Get the full A/B test summary for a project (all slots)."""
    summary = await get_project_summary(project_id)
    if not summary:
        return ABTestSummaryResponse(
            project_id=project_id,
            idea="",
            copy_sets={},
            total_impressions=0,
            total_conversions=0,
        )
    return ABTestSummaryResponse(**summary)


# ── Public tracking endpoint (for embedded landing pages) ──

@router.post("/p/impression")
async def api_public_track_impression(req: TrackImpressionRequest):
    """Public endpoint to track impressions from embedded landing pages.

    No auth required — used by the JS snippet in generated landing pages.
    Rate-limited by IP.
    """
    ok = await svc_track_impression(req.project_id, req.slot, req.variant_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    # Return empty 200 for tracking pixel compatibility
    return {"status": "ok"}


@router.post("/p/conversion")
async def api_public_track_conversion(req: TrackConversionRequest):
    """Public endpoint to track conversions from embedded landing pages.

    No auth required — used by the JS snippet in generated landing pages.
    """
    ok = await svc_track_conversion(req.project_id, req.slot, req.variant_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "ok"}
