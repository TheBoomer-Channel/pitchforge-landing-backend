"""Email verification routes — TASK-022.

Public + authenticated endpoints to manage email verification.

  * GET  /api/v1/email-verification/status           — current status (auth)
  * POST /api/v1/email-verification/send            — send / re-send (auth)
  * GET  /api/v1/email-verification/verify?token=…  — consume token (public)
  * GET  /api/v1/email-verification/throttle        — rate-limit counters (auth)

Tokens are 24h, rate-limited to 3 sends per rolling 24h per user.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth import get_current_user
from ..database import User
from ..models.email_verification import EmailVerification
from ..services.email_service import (
    generate_verification_token,
    hash_verification_token,
    render_verification_email,
    send_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/email-verification", tags=["auth"])

# Public base URL for the verification link (where the FE handles /verify-email?token=)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5174")

MAX_SENDS_PER_DAY = 3
TOKEN_TTL_HOURS = 24


# ── Helpers ────────────────────────────────────────────


async def _count_recent_sends(user_id: str) -> int:
    """Count sends in the last 24h (rolling window)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    return await EmailVerification.find(
        EmailVerification.user_id == user_id,
        EmailVerification.last_sent_at >= cutoff,
    ).count()


async def _supersede_pending(user_id: str) -> None:
    """Mark any pending tokens for this user as superseded."""
    pending = await EmailVerification.find(
        EmailVerification.user_id == user_id,
        EmailVerification.status == "pending",
    ).to_list()
    now = datetime.now(timezone.utc)
    for ev in pending:
        ev.status = "superseded"
        ev.superseded_at = now
        await ev.save()


# ── Status ──────────────────────────────────────────────


@router.get("/status", summary="Current email verification status for the user")
async def get_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns whether the user is verified, the email on file, and
    rate-limit counters so the frontend can decide whether to show
    a "resend" button.
    """
    recent = await _count_recent_sends(user.clerk_user_id)
    return {
        "email": user.email,
        "email_verified": getattr(user, "email_verified", False) or False,
        "verified_at": (
            user.email_verified_at.isoformat()
            if getattr(user, "email_verified_at", None)
            else None
        ),
        "sends_last_24h": recent,
        "resends_remaining": max(0, MAX_SENDS_PER_DAY - recent),
        "cooldown_active": recent >= MAX_SENDS_PER_DAY,
    }


# ── Send ────────────────────────────────────────────────


@router.post("/send", status_code=202, summary="Send (or re-send) a verification email")
async def send_verification(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Generate a fresh token, store its hash, and email the link.

    Idempotent: re-sending supersedes the old token.
    """
    if not user.email:
        raise HTTPException(
            status_code=400,
            detail="No email on file. Update your profile first.",
        )

    # Rate limit
    recent = await _count_recent_sends(user.clerk_user_id)
    if recent >= MAX_SENDS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit: max {MAX_SENDS_PER_DAY} verification emails per 24h. "
                   f"Try again later.",
        )

    # Supersede any pending tokens for this user
    await _supersede_pending(user.clerk_user_id)

    # Generate new token
    token, token_hash = generate_verification_token()
    now = datetime.now(timezone.utc)
    ev = EmailVerification(
        user_id=user.clerk_user_id,
        email=user.email,
        token_hash=token_hash,
        expires_at=now + timedelta(hours=TOKEN_TTL_HOURS),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        last_sent_at=now,
    )
    await ev.insert()

    # Build the verification URL
    verification_url = (
        f"{PUBLIC_BASE_URL}/verify-email?token={token}"
    )

    # Send the email
    msg = render_verification_email(verification_url, lang="en")
    msg.to = user.email
    result = await send_email(msg)

    if not result.ok:
        logger.error(f"Failed to send verification email: {result.error}")
        # Don't expose the transport error to the user, but mark the
        # verification row as "send_failed" for debugging.
        ev.status = "send_failed"
        await ev.save()
        raise HTTPException(
            status_code=502,
            detail="Could not send verification email. Please try again later.",
        )

    logger.info(
        f"Verification email sent: user={user.clerk_user_id} "
        f"transport={result.transport} to={user.email}",
    )

    response = {
        "status": "sent",
        "expires_at": ev.expires_at.isoformat(),
        "transport": result.transport,
    }
    # In dev/log mode, surface the link so the developer can click it
    if result.transport == "log" and result.console_url:
        response["dev_url"] = result.console_url
    # Always surface the URL when the transport is "log" regardless of
    # whether the transport impl returned it explicitly
    if result.transport == "log":
        response["dev_url"] = verification_url
    return response


# ── Verify (consume token) ──────────────────────────────


@router.get("/verify", summary="Consume a verification token and mark the user as verified")
async def verify_token(
    token: str = Query(..., min_length=20, max_length=128),
) -> dict:
    """Public endpoint. Validates the token, marks the user as verified.

    Idempotent: replaying a valid (but already-used) token returns success
    without re-marking.
    """
    token_hash = hash_verification_token(token)

    ev = await EmailVerification.find_one(
        EmailVerification.token_hash == token_hash,
    )
    if not ev:
        # Could be a tampered token or a deleted record
        raise HTTPException(
            status_code=400,
            detail="Invalid or unknown verification token.",
        )

    if ev.status == "used":
        return {
            "status": "already_verified",
            "email": ev.email,
            "verified_at": ev.used_at.isoformat() if ev.used_at else None,
        }

    if ev.status == "superseded":
        raise HTTPException(
            status_code=400,
            detail="This verification link has been superseded by a newer one. "
                   "Please use the most recent email.",
        )

    if ev.expires_at < datetime.now(timezone.utc):
        ev.status = "expired"
        await ev.save()
        raise HTTPException(
            status_code=400,
            detail="This verification link has expired. Please request a new one.",
        )

    # Mark verification as used
    ev.status = "used"
    ev.used_at = datetime.now(timezone.utc)
    await ev.save()

    # Mark the user as verified
    user = await User.find_one(User.clerk_user_id == ev.user_id)
    if user:
        user.email_verified = True
        user.email_verified_at = ev.used_at
        await user.save()
        logger.info(f"Email verified: user={user.clerk_user_id} email={ev.email}")
    else:
        # User deleted between issuing the token and verifying
        logger.warning(
            f"Verification token consumed for missing user {ev.user_id} — token={ev.id}",
        )

    return {
        "status": "verified",
        "email": ev.email,
        "verified_at": ev.used_at.isoformat(),
    }
