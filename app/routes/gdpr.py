"""GDPR data-subject routes — TASK-010.

Implements the rights granted by GDPR Art. 15-22:

  * GET    /api/v1/users/me/export             — Art. 20 right to portability
  * DELETE /api/v1/users/me                    — Art. 17 right to erasure
                                                 (30-day soft delete with
                                                 cancellation window)
  * POST   /api/v1/users/me/cancel-deletion    — cancel a pending deletion
  * GET    /api/v1/users/me/deletion-status    — status of pending request
  * GET    /api/v1/users/me/consents           — list of recorded consents
  * POST   /api/v1/users/me/consents           — record consent withdrawal /
                                                 grant for a specific purpose
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from ..auth import get_current_user
from ..database import (
    ApiKey,
    Job,
    Payment,
    Project,
    ResearchResult,
    TokenPurchase,
    TokenUsage,
    User,
)
from ..models.legal import (
    ConsentRecord,
    DataDeletionRequest,
    DataExportRequest,
    UserLegalAcceptance,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users/me", tags=["gdpr"])


# ── Export (Art. 20) ───────────────────────────────────


@router.get("/export", summary="GDPR Art. 20 — Download all data we hold about you")
async def export_my_data(
    request: Request,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Returns a JSON dump of all data we hold about the user.

    Includes: account profile, projects, research results, jobs, payments,
    token usage, token purchases, API keys (prefix + name only, never the
    hash), legal acceptances, consent records, deletion requests.
    """
    uid = user.clerk_user_id

    # Fan out queries in parallel-ish (Beanie uses asyncio under the hood)
    projects = await Project.find(Project.user_id == uid).to_list()
    project_ids = [p.id for p in projects]

    research = await ResearchResult.find(
        ResearchResult.project_id.in_(project_ids) if project_ids else None
    ).to_list() if project_ids else []

    jobs = await Job.find(Job.project_id.in_(project_ids) if project_ids else None).to_list() if project_ids else []
    payments = await Payment.find(Payment.user_id == uid).to_list()
    token_usage = await TokenUsage.find(TokenUsage.user_id == uid).to_list()
    token_purchases = await TokenPurchase.find(TokenPurchase.user_id == uid).to_list()
    api_keys = await ApiKey.find(ApiKey.user_id == uid, ApiKey.is_active == True).to_list()
    legal_acceptances = await UserLegalAcceptance.find(
        UserLegalAcceptance.user_id == uid
    ).to_list()
    consents = await ConsentRecord.find(ConsentRecord.user_id == uid).to_list()
    deletion = await DataDeletionRequest.find_one(
        DataDeletionRequest.user_id == uid
    )

    # Sanitize: never include key_hash, never include raw github_token
    def _project_to_dict(p: Project) -> dict:
        d = p.model_dump(mode="json", exclude={"github_token"})
        return d

    def _api_key_to_dict(k: ApiKey) -> dict:
        return {
            "id": k.id,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "key_last4": k.key_prefix[-4:] if k.key_prefix else None,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        }

    payload = {
        "export_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": uid,
            "format_version": "1.0.0",
            "policy": "GDPR Art. 20 — Right to data portability",
        },
        "profile": {
            "clerk_user_id": user.clerk_user_id,
            "email": user.email,
            "name": user.name,
            "tier": user.tier,
            "stripe_customer_id": user.stripe_customer_id,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "projects": [_project_to_dict(p) for p in projects],
        "research_results": [r.model_dump(mode="json") for r in research],
        "jobs": [j.model_dump(mode="json") for j in jobs],
        "payments": [p.model_dump(mode="json") for p in payments],
        "token_usage": [t.model_dump(mode="json") for t in token_usage],
        "token_purchases": [t.model_dump(mode="json") for t in token_purchases],
        "api_keys": [_api_key_to_dict(k) for k in api_keys],
        "legal_acceptances": [a.model_dump(mode="json") for a in legal_acceptances],
        "consent_records": [c.model_dump(mode="json") for c in consents],
        "deletion_request": deletion.model_dump(mode="json") if deletion else None,
    }

    # Audit
    payload_bytes = len(json.dumps(payload, default=str).encode("utf-8"))
    await DataExportRequest(
        user_id=uid,
        completed_at=datetime.now(timezone.utc),
        file_size_bytes=payload_bytes,
        status="ready",
        download_count=1,
        ip=request.client.host if request.client else None,
    ).insert()

    logger.info(f"GDPR export: user={uid} bytes={payload_bytes}")
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": (
                f'attachment; filename="pitchforge-data-export-{uid[:8]}-'
                f'{datetime.now(timezone.utc).strftime("%Y%m%d")}.json"'
            ),
        },
    )


# ── Deletion (Art. 17) ─────────────────────────────────


@router.delete("", status_code=202, summary="GDPR Art. 17 — Request account deletion (30-day soft delete)")
async def request_deletion(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Soft-delete the account. Data is retained 30 days in case you
    change your mind; then hard-deleted by a background job.
    """
    existing = await DataDeletionRequest.find_one(
        DataDeletionRequest.user_id == user.clerk_user_id
    )
    if existing and existing.status == "pending":
        return {
            "status": "already_pending",
            "requested_at": existing.requested_at.isoformat(),
            "scheduled_hard_delete_at": existing.scheduled_hard_delete_at.isoformat(),
            "cancel_url": "/api/v1/users/me/cancel-deletion",
            "message": "You already have a pending deletion request.",
        }

    if existing and existing.status == "completed":
        raise HTTPException(
            status_code=410,
            detail="Account already permanently deleted.",
        )

    req = DataDeletionRequest(
        user_id=user.clerk_user_id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        status="pending",
    )
    if existing:
        # Re-request after a previous cancellation
        existing.status = "pending"
        existing.requested_at = datetime.now(timezone.utc)
        existing.scheduled_hard_delete_at = req.scheduled_hard_delete_at
        existing.cancelled_at = None
        existing.completed_at = None
        await existing.save()
    else:
        await req.insert()

    logger.warning(
        f"GDPR deletion requested: user={user.clerk_user_id} "
        f"hard_delete_at={req.scheduled_hard_delete_at.isoformat()}",
    )
    return {
        "status": "pending",
        "requested_at": req.requested_at.isoformat(),
        "scheduled_hard_delete_at": req.scheduled_hard_delete_at.isoformat(),
        "cancel_url": "/api/v1/users/me/cancel-deletion",
        "message": (
            "Your account is scheduled for permanent deletion in 30 days. "
            "Log in within that window to cancel."
        ),
    }


@router.post("/cancel-deletion", summary="Cancel a pending deletion request")
async def cancel_deletion(
    user: User = Depends(get_current_user),
) -> dict:
    req = await DataDeletionRequest.find_one(
        DataDeletionRequest.user_id == user.clerk_user_id
    )
    if not req or req.status != "pending":
        raise HTTPException(
            status_code=404,
            detail="No pending deletion request to cancel.",
        )
    req.status = "cancelled"
    req.cancelled_at = datetime.now(timezone.utc)
    await req.save()
    logger.info(f"GDPR deletion cancelled: user={user.clerk_user_id}")
    return {"status": "cancelled", "cancelled_at": req.cancelled_at.isoformat()}


@router.get("/deletion-status", summary="Status of the current deletion request")
async def deletion_status(
    user: User = Depends(get_current_user),
) -> dict:
    req = await DataDeletionRequest.find_one(
        DataDeletionRequest.user_id == user.clerk_user_id
    )
    if not req:
        return {"status": "none"}
    return {
        "status": req.status,
        "requested_at": req.requested_at.isoformat() if req.requested_at else None,
        "scheduled_hard_delete_at": (
            req.scheduled_hard_delete_at.isoformat()
            if req.scheduled_hard_delete_at
            else None
        ),
        "cancelled_at": req.cancelled_at.isoformat() if req.cancelled_at else None,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
    }


# ── Consents (Art. 7) ──────────────────────────────────


@router.get("/consents", summary="List all recorded consent decisions")
async def list_consents(
    user: User = Depends(get_current_user),
) -> list[dict]:
    records = await ConsentRecord.find(
        ConsentRecord.user_id == user.clerk_user_id
    ).sort("-granted_at").to_list()
    return [r.model_dump(mode="json") for r in records]


@router.post("/consents", summary="Record a consent decision")
async def record_consent(
    request: Request,
    user: User = Depends(get_current_user),
):
    body = await request.json()
    purpose = body.get("purpose")
    granted = body.get("granted")
    if not purpose or not isinstance(granted, bool):
        raise HTTPException(
            status_code=400,
            detail="Body must be {purpose: str, granted: bool}",
        )

    await ConsentRecord(
        user_id=user.clerk_user_id,
        purpose=purpose,
        granted=granted,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        method=body.get("method", "settings"),
    ).insert()
    logger.info(
        f"Consent recorded: user={user.clerk_user_id} "
        f"purpose={purpose} granted={granted}",
    )
    return Response(status_code=204)
