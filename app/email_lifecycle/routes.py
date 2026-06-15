"""Email lifecycle routes — TASK-040.

  * POST /api/v1/email/webhook          — Resend open/click/delivery webhooks
  * GET  /api/v1/email/unsubscribe      — One-click unsubscribe (public)
  * GET  /api/v1/email/preferences       — User email preferences (auth)
  * PATCH /api/v1/email/preferences      — Update email preferences (auth)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import User
from .models import EmailEvent, UnsubscribeToken
from .templates import consume_unsubscribe_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/email", tags=["email"])

RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET", "")
EMAIL_LIFECYCLE_ENABLED = os.getenv("EMAIL_LIFECYCLE_ENABLED", "true").lower() == "true"


# ── Schemas ──────────────────────────────────────────────


class EmailPreferencesResponse(BaseModel):
    email_verified: bool
    marketing_emails: bool = True
    product_emails: bool = True
    unsubscribed: bool = False


class UpdatePreferencesRequest(BaseModel):
    marketing_emails: bool | None = None
    product_emails: bool | None = None


# ── Resend Webhook ──────────────────────────────────────


@router.post("/webhook", summary="Resend webhook: open, click, delivery events")
async def resend_webhook(request: Request) -> dict:
    """Receive Resend webhook events and update EmailEvent records.

    Resend sends these event types:
      * email.sent        → mark as sent
      * email.delivered   → mark as delivered
      * email.opened      → mark first open timestamp
      * email.clicked     → mark first click timestamp
      * email.bounced     → mark as bounced
      * email.complained  → mark as spam complaint
    """
    if not EMAIL_LIFECYCLE_ENABLED:
        return {"status": "disabled"}

    body = await request.body()

    # Verify webhook signature (Resend uses Svix under the hood)
    if RESEND_WEBHOOK_SECRET:
        svix_id = request.headers.get("svix-id", "")
        svix_timestamp = request.headers.get("svix-timestamp", "")
        svix_signature = request.headers.get("svix-signature", "")

        if svix_id and svix_timestamp and svix_signature:
            # Svix v1 signature verification
            signed_content = f"{svix_id}.{svix_timestamp}.{body.decode('utf-8')}"
            expected = hmac.new(
                RESEND_WEBHOOK_SECRET.encode("utf-8"),
                signed_content.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            # Compare signatures in constant time
            signatures = svix_signature.split(" ")
            valid = any(
                hmac.compare_digest(sig.split(",", 1)[1] if "," in sig else sig, expected)
                for sig in signatures
            )
            if not valid:
                logger.warning("Invalid Resend webhook signature")
                raise HTTPException(status_code=401, detail="Invalid webhook signature"            )
    else:
        pass  # body already read above

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type", "")
    data = payload.get("data", {})
    resend_id = data.get("email_id", "")

    if not resend_id:
        return {"status": "ignored", "reason": "no email_id"}

    # Find the corresponding EmailEvent
    event = await EmailEvent.find_one(EmailEvent.resend_id == resend_id)
    if not event:
        logger.debug(f"Webhook for unknown email: {resend_id}")
        return {"status": "ignored", "reason": "unknown email_id"}

    now = datetime.now(timezone.utc)

    if event_type == "email.delivered":
        if event.status in ("sent", "pending"):
            event.status = "delivered"
            await event.save()
            logger.info(f"Email delivered: {resend_id} to {event.to_email}")

    elif event_type == "email.opened":
        if event.opened_at is None:
            event.opened_at = now
            event.status = "opened"
            await event.save()
            logger.info(f"Email opened: {resend_id} by {event.user_id}")

    elif event_type == "email.clicked":
        if event.clicked_at is None:
            event.clicked_at = now
            event.status = "clicked"
            await event.save()
            logger.info(f"Email clicked: {resend_id} by {event.user_id}")

    elif event_type == "email.bounced":
        event.status = "bounced"
        event.error = "bounced"
        await event.save()
        logger.warning(f"Email bounced: {resend_id} to {event.to_email}")

    elif event_type == "email.complained":
        event.status = "complained"
        event.error = "spam_complaint"
        await event.save()
        # Auto-unsubscribe on spam complaint
        user = await User.find_one(User.clerk_user_id == event.user_id)
        if user:
            user.email_opt_out = True
            await user.save()
        logger.warning(f"Spam complaint: {resend_id} from {event.to_email}")

    return {"status": "processed", "event_type": event_type}


# ── Unsubscribe ────────────────────────────────────────


@router.get("/unsubscribe", summary="One-click unsubscribe (GDPR compliant)")
async def unsubscribe(
    token: str = Query(..., min_length=20, max_length=128),
) -> dict:
    """Public endpoint. Consumes the unsubscribe token and opts the user out
    of all marketing/product emails.
    """
    user_id = await consume_unsubscribe_token(token)
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired unsubscribe token. Please contact support.",
        )

    user = await User.find_one(User.clerk_user_id == user_id)
    if user:
        user.email_opt_out = True
        await user.save()
        logger.info(f"User unsubscribed: {user_id} ({user.email})")

    return {
        "status": "unsubscribed",
        "message": "You have been unsubscribed from all PitchForge emails. "
                   "You will still receive transactional emails (password reset, billing receipts).",
    }


# ── Preferences ────────────────────────────────────────


@router.get("/preferences", response_model=EmailPreferencesResponse, summary="Get email preferences")
async def get_preferences(user: User = Depends(get_current_user)) -> EmailPreferencesResponse:
    """Return the current email preferences for the authenticated user."""
    return EmailPreferencesResponse(
        email_verified=getattr(user, "email_verified", False) or False,
        unsubscribed=getattr(user, "email_opt_out", False) or False,
    )


@router.patch("/preferences", response_model=EmailPreferencesResponse, summary="Update email preferences")
async def update_preferences(
    body: UpdatePreferencesRequest,
    user: User = Depends(get_current_user),
) -> EmailPreferencesResponse:
    """Update email preferences for the authenticated user."""
    # If user explicitly enables marketing emails, clear the opt-out
    if body.marketing_emails is True and getattr(user, "email_opt_out", False):
        user.email_opt_out = False
        await user.save()
    elif body.marketing_emails is False:
        user.email_opt_out = True
        await user.save()

    return EmailPreferencesResponse(
        email_verified=getattr(user, "email_verified", False) or False,
        unsubscribed=getattr(user, "email_opt_out", False) or False,
    )
