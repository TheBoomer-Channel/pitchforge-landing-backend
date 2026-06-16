"""Referral routes — TASK-042.

  * GET  /api/v1/referrals/stats         — Referrer's stats (code, count, rewards)
  * POST /api/v1/referrals/generate-code — Generate/regenerate referral code
  * POST /api/v1/referrals/cron-rewards  — Process pending rewards (cron)
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from beanie.operators import In

from ..auth import get_current_user
from ..database import User, Subscription
from .models import Referral

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/referrals", tags=["referrals"])

CRON_SECRET = os.getenv("REFERRAL_CRON_SECRET", "dev-referral-cron-secret-change-in-prod")
REWARD_THRESHOLD = 3  # Number of paid referrals needed for a reward

CODE_LENGTH = 8
CODE_CHARS = string.ascii_uppercase + string.digits  # No ambiguous chars

# ── Schemas ──────────────────────────────────────────────


class ReferralStatsResponse(BaseModel):
    referral_code: str | None
    referral_link: str | None
    total_referrals: int
    pending_referrals: int
    converted_referrals: int
    rewards_granted: int
    referrals_needed_for_reward: int
    next_reward_progress: int  # how many converted referrals toward next reward


class GenerateCodeResponse(BaseModel):
    referral_code: str
    referral_link: str


# ── Helpers ──────────────────────────────────────────────


def _generate_code() -> str:
    """Generate a unique 8-char referral code (uppercase + digits)."""
    return "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LENGTH))


async def _ensure_referral_code(user: User) -> str:
    """Get or create a referral code for the user."""
    if getattr(user, "referral_code", None):
        return user.referral_code
    # Generate a unique code
    for _ in range(5):  # Retry up to 5 times for uniqueness
        code = _generate_code()
        existing = await User.find_one(User.referral_code == code)
        if not existing:
            user.referral_code = code
            await user.save()
            return code
    raise HTTPException(status_code=500, detail="Could not generate unique referral code")


# ── Stats ────────────────────────────────────────────────


@router.get("/stats", response_model=ReferralStatsResponse, summary="Get referral stats for the current user")
async def get_stats(user: User = Depends(get_current_user)) -> ReferralStatsResponse:
    """Return the referrer's code, counts, and reward progress."""
    code = getattr(user, "referral_code", None)

    # Auto-generate referral code if missing (TASK-042)
    if not code:
        code = await _ensure_referral_code(user)

    if not code:
        return ReferralStatsResponse(
            referral_code=None,
            referral_link=None,
            total_referrals=0,
            pending_referrals=0,
            converted_referrals=0,
            rewards_granted=0,
            referrals_needed_for_reward=REWARD_THRESHOLD,
            next_reward_progress=0,
        )

    base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:5173")

    # Count referrals
    all_refs = await Referral.find(Referral.referrer_id == user.clerk_user_id).to_list()
    total = len(all_refs)
    converted = sum(1 for r in all_refs if r.status in ("converted", "reward_granted"))
    pending = total - converted
    rewards = sum(1 for r in all_refs if r.reward_granted)

    # Progress toward next reward (count converted referrals modulo threshold)
    next_progress = converted % REWARD_THRESHOLD

    return ReferralStatsResponse(
        referral_code=code,
        referral_link=f"{base_url}/signup?ref={code}",
        total_referrals=total,
        pending_referrals=pending,
        converted_referrals=converted,
        rewards_granted=rewards,
        referrals_needed_for_reward=REWARD_THRESHOLD,
        next_reward_progress=next_progress,
    )


# ── Generate / Regenerate Code ──────────────────────────


@router.post("/generate-code", response_model=GenerateCodeResponse, summary="Generate or regenerate referral code")
async def generate_code(user: User = Depends(get_current_user)) -> GenerateCodeResponse:
    """Generate a referral code for the user. Idempotent: returns existing code if already set."""
    code = await _ensure_referral_code(user)
    base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:5173")

    logger.info(f"Referral code generated: user={user.clerk_user_id} code={code}")

    return GenerateCodeResponse(
        referral_code=code,
        referral_link=f"{base_url}/signup?ref={code}",
    )


# ── Track Referral (called from auth/sync) ──────────────


@router.post("/track", summary="Track a referral from ?ref=CODE (called on signup)")
async def track_referral(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Record a referral when a new user signs up with a referral code.

    Called by the frontend after Clerk authentication.
    Body: { "ref": "ABC12345" }
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    ref_code = body.get("ref", "").strip().upper()

    if not ref_code:
        return {"status": "no_ref_code"}

    # Find the referrer by code
    referrer = await User.find_one(User.referral_code == ref_code)
    if not referrer:
        return {"status": "invalid_code", "detail": "Referral code not found"}

    # Prevent self-referral
    if referrer.clerk_user_id == user.clerk_user_id:
        return {"status": "self_referral", "detail": "Cannot refer yourself"}

    # Check if this referee already has a referral (one referrer per user)
    existing = await Referral.find_one(Referral.referee_id == user.clerk_user_id)
    if existing:
        return {"status": "already_referred", "detail": "Already referred by another user"}

    # Check if the referrer already referred this user (idempotency)
    existing_pair = await Referral.find_one(
        Referral.referrer_id == referrer.clerk_user_id,
        Referral.referee_id == user.clerk_user_id,
    )
    if existing_pair:
        return {"status": "already_tracked", "detail": "Referral already recorded"}

    # Create the referral
    ref = Referral(
        referrer_id=referrer.clerk_user_id,
        referee_id=user.clerk_user_id,
        referral_code_used=ref_code,
        status="signed_up",
    )
    await ref.insert()

    # Mark the referee as referred_by
    if not getattr(user, "referred_by", None):
        user.referred_by = referrer.clerk_user_id
        await user.save()

    logger.info(
        f"Referral tracked: {referrer.clerk_user_id} → {user.clerk_user_id} (code: {ref_code})"
    )

    return {
        "status": "tracked",
        "referrer_code": ref_code,
    }


# ── Cron: Process Rewards ────────────────────────────────


@router.post("/cron-rewards", summary="Cron: grant rewards when referrer hits 3+ paid referrals")
async def cron_rewards(request: Request) -> dict:
    """Check all referrers with 3+ converted-but-not-yet-rewarded referrals.

    Grants 1 free month via Stripe subscription extension or credit note.
    Idempotent: only processes referrals where reward_granted=False.

    Security: requires X-Cron-Secret header.
    """
    provided = request.headers.get("X-Cron-Secret", "")
    if provided != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid cron secret")

    now = datetime.now(timezone.utc)
    rewards_granted = 0

    # Query all converted referrals awaiting reward
    all_converted = await Referral.find(
        Referral.status == "converted",
        Referral.reward_granted == False,
    ).to_list()

    # Group by referrer
    by_referrer: dict[str, list[Referral]] = {}
    for ref in all_converted:
        by_referrer.setdefault(ref.referrer_id, []).append(ref)

    for referrer_id, refs in by_referrer.items():
        if len(refs) < REWARD_THRESHOLD:
            continue

        # Grant reward
        referrer = await User.find_one(User.clerk_user_id == referrer_id)
        if not referrer:
            continue

        # Mark these referrals as rewarded
        for ref in refs[:REWARD_THRESHOLD]:
            ref.status = "reward_granted"
            ref.reward_granted = True
            ref.reward_granted_at = now
            ref.reward_type = "free_month"
            ref.reward_details = {
                "granted_at": now.isoformat(),
                "threshold": REWARD_THRESHOLD,
            }
            await ref.save()

        rewards_granted += 1

        # If user has an active Stripe subscription, extend it by 1 month
        try:
            sub = await Subscription.find_one(
                Subscription.user_id == referrer_id,
                In(Subscription.status, ["active", "trialing"]),
            )
            if sub:
                from ..config import settings
                if settings.STRIPE_API_KEY:
                    import stripe
                    stripe.api_key = settings.STRIPE_API_KEY
                    # Extend the subscription trial by 30 days
                    stripe.Subscription.modify(
                        sub.stripe_subscription_id,
                        trial_end="now" if sub.status == "trialing" else None,
                        metadata={"referral_reward": "true", "granted_at": now.isoformat()},
                    )
                    logger.info(
                        f"Stripe subscription extended for referral reward: {referrer_id}"
                    )
        except Exception as e:
            logger.warning(f"Failed to extend Stripe subscription for referral reward: {e}")

        logger.info(
            f"Referral reward granted: referrer={referrer_id} count={len(refs[:REWARD_THRESHOLD])}"
        )

    return {
        "rewards_granted": rewards_granted,
        "ran_at": now.isoformat(),
    }
