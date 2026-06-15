"""Free trial routes — TASK-018.

14-day Pro trial, no credit card required. Lifecycle:
  * Day 0 (signup): start trial, trial_ends_at = now + 14d
  * Day 1:  welcome email
  * Day 7:  "you're getting value" email
  * Day 11: "3 days left" email
  * Day 13: "1 day left" email
  * Day 14: expiry → tier reverts to 'free', email "we hope you enjoyed"

Extensions: a user may request ONE 7-day extension (no card required).

Cron endpoint: POST /api/v1/trial/cron-daily
  * Run at 09:00 UTC daily
  * Sends the appropriate lifecycle email
  * Expires trials where trial_ends_at < now and tier == 'pro' and no Stripe sub
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import User, Subscription
from ..models.audit import AuditAction
from ..services.audit_service import audit
from ..email_lifecycle.templates import (
    send_upgrade_prompt_email,
    send_winback_email,
    send_activation_email,
    send_welcome_email,
)
from ..email_lifecycle.models import EmailEvent
from ..services.email_service import send_email, EmailMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trial", tags=["billing"])

TRIAL_DURATION = timedelta(days=14)
EXTENSION_DURATION = timedelta(days=7)
CRON_SECRET = os.getenv("TRIAL_CRON_SECRET", "dev-cron-secret-change-in-prod")


# ── Expired email (kept inline — simple enough) ────────


def _expired_email(to: str) -> EmailMessage:
    return EmailMessage(
        to=to,
        subject="Your PitchForge Pro trial has ended",
        text=(
            "Hi,\n\n"
            "Your 14-day Pro trial has ended and your account has been switched to the Free tier.\n\n"
            "You can still:\n"
            "  • Research up to 1 idea per day\n"
            "  • Create up to 3 projects per month\n"
            "  • Use 2,000 tokens for code generation\n\n"
            "Whenever you're ready to come back to Pro, plans start at €9/month.\n\n"
            "— The PitchForge team"
        ),
    )


# ── Schemas ──────────────────────────────────────────────


class TrialStartResponse(BaseModel):
    trial_started: bool
    trial_ends_at: str
    already_trialed: bool


class TrialStatusResponse(BaseModel):
    in_trial: bool
    trial_started_at: str | None
    trial_ends_at: str | None
    days_remaining: int
    has_active_subscription: bool
    effective_tier: str  # what the user actually gets right now


# ── Status ──────────────────────────────────────────────


@router.get("/status", response_model=TrialStatusResponse, summary="Current trial status")
async def get_status(user: User = Depends(get_current_user)) -> TrialStatusResponse:
    now = datetime.now(timezone.utc)
    trial_ends = user.trial_ends_at
    if trial_ends and trial_ends.tzinfo is None:
        trial_ends = trial_ends.replace(tzinfo=timezone.utc)
    in_trial = bool(
        trial_ends and now < trial_ends and user.tier in ("pro", "starter", "code_mvp")
    )
    days_remaining = max(0, ((trial_ends - now).days if trial_ends else 0))

    has_sub = False
    sub = await Subscription.find_one(
        Subscription.user_id == user.clerk_user_id,
        Subscription.status.in_(["active", "trialing"]),
    )
    has_sub = sub is not None

    # Effective tier: if trial has expired but tier is still "pro", effective = "free"
    effective = user.tier
    if not in_trial and not has_sub and user.tier in ("pro", "starter", "code_mvp"):
        # Don't downgrade automatically here — the cron does that. But surface the
        # would-be-effective tier so the frontend can warn.
        if trial_ends and now > trial_ends:
            effective = "free"

    return TrialStatusResponse(
        in_trial=in_trial,
        trial_started_at=(
            user.trial_started_at.isoformat() if user.trial_started_at else None
        ),
        trial_ends_at=trial_ends.isoformat() if trial_ends else None,
        days_remaining=days_remaining,
        has_active_subscription=has_sub,
        effective_tier=effective,
    )


# ── Start ───────────────────────────────────────────────


@router.post("/start", response_model=TrialStartResponse, summary="Start a 14-day Pro trial (no card required)")
async def start_trial(
    user: User = Depends(get_current_user),
) -> TrialStartResponse:
    """Starts the trial if the user has never had one.
    Idempotent: re-calling does NOT extend.
    """
    if user.trial_ends_at:
        # Already started (or expired)
        return TrialStartResponse(
            trial_started=False,
            trial_ends_at=user.trial_ends_at.isoformat(),
            already_trialed=True,
        )

    # Don't start a trial if the user has an active paid subscription
    sub = await Subscription.find_one(
        Subscription.user_id == user.clerk_user_id,
        Subscription.status.in_(["active", "trialing"]),
    )
    if sub:
        raise HTTPException(
            status_code=400,
            detail="Cannot start a trial while you have an active paid subscription.",
        )

    now = datetime.now(timezone.utc)
    ends = now + TRIAL_DURATION
    user.trial_started_at = now
    user.trial_ends_at = ends
    # Don't overwrite an existing tier; trial is implicit Pro access
    if user.tier == "free":
        user.tier = "pro"
    await user.save()
    await audit.log(
        action=AuditAction.ACCOUNT_TRIAL_STARTED if hasattr(AuditAction, "ACCOUNT_TRIAL_STARTED")
                 else AuditAction.ACCOUNT_CREATED,
        user_id=user.clerk_user_id,
        user_email=user.email,
        target_type="user",
        target_id=user.clerk_user_id,
        metadata={"trial_ends_at": ends.isoformat(), "duration_days": 14},
    )
    # Welcome email — use the new lifecycle template
    if user.email and not getattr(user, 'email_opt_out', False):
        try:
            await send_welcome_email(
                user_id=user.clerk_user_id,
                to_email=user.email,
                name=user.name or "",
            )
        except Exception as e:
            logger.warning(f"Welcome email send failed: {e}")
    logger.info(f"Trial started: user={user.clerk_user_id} ends={ends.isoformat()}")
    return TrialStartResponse(
        trial_started=True,
        trial_ends_at=ends.isoformat(),
        already_trialed=False,
    )


# ── Extend (one-time) ──────────────────────────────────


class ExtendResponse(BaseModel):
    extended: bool
    trial_ends_at: str
    reason: str


@router.post("/extend", response_model=ExtendResponse, summary="Extend trial by 7 days (one-time, no card)")
async def extend_trial(user: User = Depends(get_current_user)) -> ExtendResponse:
    if not user.trial_ends_at:
        raise HTTPException(status_code=400, detail="No trial to extend")
    if user.trial_extended:
        raise HTTPException(status_code=400, detail="Trial already extended once")
    # Only allow while still in trial
    if datetime.now(timezone.utc) > user.trial_ends_at:
        raise HTTPException(status_code=400, detail="Trial has already expired")

    new_end = user.trial_ends_at + EXTENSION_DURATION
    user.trial_ends_at = new_end
    user.trial_extended = True
    await user.save()
    await audit.log(
        action="trial.extended",
        user_id=user.clerk_user_id,
        user_email=user.email,
        metadata={"new_trial_ends_at": new_end.isoformat(), "extension_days": 7},
    )
    return ExtendResponse(
        extended=True,
        trial_ends_at=new_end.isoformat(),
        reason="7-day extension granted (one-time)",
    )


# ── Cron: send lifecycle emails + expire trials ─────────


@router.post("/cron-daily", summary="Daily cron: send lifecycle emails + expire trials")
async def cron_daily(request: Request) -> dict:
    """Called daily at 09:00 UTC. Idempotent: emails are sent once per (user, day).

    Security: requires X-Cron-Secret header. In production, only the cron
    runner should know the secret.
    """
    provided = request.headers.get("X-Cron-Secret", "")
    if provided != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    now = datetime.now(timezone.utc)
    today = now.date()

    # 1) Expire trials past their end-date that have no active subscription
    expired_count = 0
    candidates = await User.find(
        User.trial_ends_at != None,
        User.tier != "free",
    ).to_list()
    for user in candidates:
        if user.trial_ends_at and user.trial_ends_at.tzinfo is None:
            user.trial_ends_at = user.trial_ends_at.replace(tzinfo=timezone.utc)
        if not (user.trial_ends_at and now > user.trial_ends_at):
            continue
        # Check they don't have an active subscription
        sub = await Subscription.find_one(
            Subscription.user_id == user.clerk_user_id,
            Subscription.status.in_(["active", "trialing"]),
        )
        if sub:
            continue
        # Expire
        user.tier = "free"
        await user.save()
        if user.email and not getattr(user, 'email_opt_out', False):
            try:
                await send_email(_expired_email(user.email))
            except Exception as e:
                logger.warning(f"Expired email send failed: {e}")
        await audit.log(
            action=AuditAction.SETTINGS_TIER_CHANGED,
            user_id=user.clerk_user_id,
            user_email=user.email,
            target_type="user",
            target_id=user.clerk_user_id,
            metadata={"new_tier": "free", "reason": "trial_expired"},
        )
        expired_count += 1

    # 2) Send day-7 / 11 / 13 upgrade prompt emails using new templates
    emails_sent = 0
    for day, _label in [(7, "week"), (11, "t-3d"), (13, "t-1d")]:
        days_left = 14 - day
        target_window_start = now - timedelta(days=day, hours=2)
        target_window_end = now - timedelta(days=day - 1, hours=-2)
        users = await User.find(
            User.trial_started_at >= target_window_start,
            User.trial_started_at < target_window_end,
            User.tier != "free",
        ).to_list()
        for user in users:
            if not user.email:
                continue
            if getattr(user, 'email_opt_out', False):
                continue
            # Idempotency: check if we already sent an upgrade prompt
            already = await EmailEvent.find_one(
                EmailEvent.user_id == user.clerk_user_id,
                EmailEvent.email_type == "upgrade_prompt",
            )
            if already:
                continue
            try:
                await send_upgrade_prompt_email(
                    user_id=user.clerk_user_id,
                    to_email=user.email,
                    name=user.name or "",
                    days_left=days_left,
                )
                emails_sent += 1
            except Exception as e:
                logger.warning(f"Upgrade prompt email failed: {e}")

    # 3) Send activation emails to active trial users (day 3-6) with idempotency
    for day in range(3, 7):
        target_window_start = now - timedelta(days=day, hours=2)
        target_window_end = now - timedelta(days=day - 1, hours=-2)
        users = await User.find(
            User.trial_started_at >= target_window_start,
            User.trial_started_at < target_window_end,
            User.tier != "free",
        ).to_list()
        for user in users:
            if not user.email:
                continue
            if getattr(user, 'email_opt_out', False):
                continue
            # Idempotency: check if we already sent an activation email
            already = await EmailEvent.find_one(
                EmailEvent.user_id == user.clerk_user_id,
                EmailEvent.email_type == "activation",
            )
            if already:
                continue
            try:
                await send_activation_email(
                    user_id=user.clerk_user_id,
                    to_email=user.email,
                    name=user.name or "",
                    days_active=day,
                )
                emails_sent += 1
            except Exception as e:
                logger.warning(f"Activation email failed: {e}")

    # 4) Send win-back emails: trial expired 14-21 days ago, no active sub, not already sent
    winback_start = now - timedelta(days=21)
    winback_end = now - timedelta(days=14)
    candidates = await User.find(
        User.trial_ends_at >= winback_start,
        User.trial_ends_at < winback_end,
        User.tier == "free",
    ).to_list()
    for user in candidates:
        if not user.email:
            continue
        if getattr(user, 'email_opt_out', False):
            continue
        # Check for active subscription
        sub = await Subscription.find_one(
            Subscription.user_id == user.clerk_user_id,
            Subscription.status.in_(["active", "trialing"]),
        )
        if sub:
            continue
        # Check if we already sent a winback (idempotency via EmailEvent)
        already = await EmailEvent.find_one(
            EmailEvent.user_id == user.clerk_user_id,
            EmailEvent.email_type == "winback",
        )
        if already:
            continue
        try:
            days_since = (now - user.trial_ends_at.replace(tzinfo=timezone.utc)).days
            await send_winback_email(
                user_id=user.clerk_user_id,
                to_email=user.email,
                name=user.name or "",
                days_since_expiry=days_since,
            )
            emails_sent += 1
        except Exception as e:
            logger.warning(f"Winback email failed: {e}")

    return {
        "expired_trials": expired_count,
        "emails_sent": emails_sent,
        "ran_at": now.isoformat(),
    }
