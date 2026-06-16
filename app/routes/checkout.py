"""Stripe checkout & webhook routes — full Stripe integration with product metadata.

Each Stripe product has metadata fields controlling user limits:
- max_tokens, max_research_per_day, max_projects_per_month

Flow:
1. User requests checkout → Stripe Checkout Session with price ID + metadata
2. Stripe sends webhook → completes payment → upgrades user tier
3. Limits are read from product metadata on the Stripe side
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from beanie.operators import In

from ..auth import get_current_user, TIER_ORDER
from ..config import settings
from ..database import User, Payment, Subscription, ProcessedWebhookEvent
from ..models.audit import AuditAction
from ..pricing import PRICE_MAP, AMOUNT_MAP
from ..services.audit_service import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["checkout"])

# Set Stripe API key once at module level
if settings.STRIPE_API_KEY:
    stripe.api_key = settings.STRIPE_API_KEY

# ── Schemas ────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    tier: str  # starter / pro / code_mvp
    project_id: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: str


# ── Endpoints ──────────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Create a Stripe Checkout session for a tier upgrade.

    Uses real Stripe price IDs from environment. Each line item includes
    metadata that Stripe sends back via webhook for fulfillment.
    """
    if body.tier not in TIER_ORDER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier: {body.tier}",
        )

    # Prevent downgrades
    current_level = TIER_ORDER.get(user.tier, 0)
    requested_level = TIER_ORDER.get(body.tier, 0)
    if requested_level <= current_level:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot downgrade from {user.tier} to {body.tier}. "
            f"Current tier is already equal or higher.",
        )

    if not settings.STRIPE_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured",
        )

    price_id = PRICE_MAP.get(body.tier)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Price not configured for tier: {body.tier}",
        )

    try:
        session_params = {
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "payment" if body.tier == "code_mvp" else "subscription",
            "success_url": str(request.base_url) + "dashboard?checkout=success",
            "cancel_url": str(request.base_url) + "dashboard?checkout=cancel",
            "metadata": {
                "user_id": str(user.id),
                "tier": body.tier,
                "project_id": body.project_id or "",
            },
        }
        # Add customer context if available
        if user.stripe_customer_id:
            session_params["customer"] = user.stripe_customer_id
        else:
            session_params["customer_email"] = user.email

        # Add subscription_data only for recurring modes
        if body.tier != "code_mvp":
            session_params["subscription_data"] = {
                "metadata": {"user_id": str(user.id), "tier": body.tier},
            }

        session = stripe.checkout.Session.create(**session_params)
    except stripe.StripeError as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe checkout creation failed",
        )

    # Record the payment attempt
    payment = Payment(
        user_id=str(user.id),
        tier=body.tier,
        amount=AMOUNT_MAP.get(body.tier, 0),
        currency="eur",
        stripe_session_id=session.id,
        status="pending",
    )
    await payment.insert()

    logger.info(f"Checkout created: user={user.email} tier={body.tier} session={session.id}")

    return CheckoutResponse(checkout_url=session.url)


@router.post("/portal", summary="Create a Stripe Customer Portal session (manage subscription, invoices, payment methods)")
async def create_portal_session(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Returns a one-time URL to the Stripe Customer Portal where the user
    can update card, download invoices, change plan, or cancel.

    Requires that the user has a `stripe_customer_id` (i.e. an active or
    past subscription). Free-tier users get a 400.
    """
    if not settings.STRIPE_API_KEY:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "No Stripe customer on file. Subscribe to a paid plan first "
                "to access the billing portal."
            ),
        )
    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=str(request.base_url) + "settings#billing",
        )
    except stripe.StripeError as e:
        logger.error(f"Stripe portal session error: {e}")
        raise HTTPException(status_code=502, detail="Could not create portal session")
    return {"portal_url": session.url}


@router.get("/subscriptions", summary="List the user's current subscriptions")
async def list_subscriptions(
    user: User = Depends(get_current_user),
) -> dict:
    subs = await Subscription.find(
        Subscription.user_id == user.clerk_user_id,
    ).sort("-created_at").to_list()
    return {
        "subscriptions": [
            {
                "id": s.id,
                "tier": s.tier,
                "status": s.status,
                "current_period_start": (
                    s.current_period_start.isoformat() if s.current_period_start else None
                ),
                "current_period_end": (
                    s.current_period_end.isoformat() if s.current_period_end else None
                ),
                "cancel_at_period_end": s.cancel_at_period_end,
                "trial_ends_at": s.trial_ends_at.isoformat() if s.trial_ends_at else None,
            }
            for s in subs
        ]
    }


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events — checkout completed, subscription updates.

    On checkout.session.completed: upgrades user tier.
    On customer.subscription.updated: handles plan changes (future).
    On customer.subscription.deleted: reverts to free tier (future).
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event["type"]
    event_id = event.get("id", "")
    data = event["data"]["object"]
    logger.info(f"Stripe webhook: {event_type} ({event_id})")

    # ── Idempotency: skip if we've already processed this event ──
    existing = await ProcessedWebhookEvent.find_one(
        ProcessedWebhookEvent.stripe_event_id == event_id,
    )
    if existing:
        logger.info(f"Skipping already-processed webhook: {event_id}")
        return {"status": "ok", "duplicate": True}

    # ── Dispatch by type ──
    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data, request)
    elif event_type == "customer.subscription.created":
        await _handle_subscription_created(data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        await _handle_subscription_ended(data)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(data)
    elif event_type == "invoice.payment_failed":
        await _handle_invoice_failed(data)
    elif event_type == "checkout.session.expired":
        session_id = data.get("id")
        payment = await Payment.find_one(Payment.stripe_session_id == session_id)
        if payment:
            payment.status = "expired"
            await payment.save()
        logger.info(f"Checkout expired: session={session_id}")
    else:
        logger.debug(f"Unhandled Stripe event type: {event_type}")

    # Mark event as processed (idempotency)
    if event_id:
        try:
            await ProcessedWebhookEvent(
                stripe_event_id=event_id,
                event_type=event_type,
            ).insert()
        except Exception as e:
            # Unique-index race: another worker got here first → fine
            logger.debug(f"ProcessedWebhookEvent insert race: {e}")

    return {"status": "ok"}


# ── Webhook Handlers ────────────────────────────────────

async def _upsert_subscription_from_stripe(
    user_id: str, stripe_sub: dict, customer_id: Optional[str] = None,
) -> Optional[Subscription]:
    """Create or update a Subscription row from a Stripe subscription object."""
    sub_id = stripe_sub.get("id")
    if not sub_id:
        return None
    tier = (
        stripe_sub.get("metadata", {}).get("tier")
        or (stripe_sub.get("items", {}).get("data", [{}])[0]
            .get("price", {}).get("metadata", {}).get("tier"))
        or "starter"
    )
    period_start = stripe_sub.get("current_period_start")
    period_end = stripe_sub.get("current_period_end")
    trial_end = stripe_sub.get("trial_end")

    existing = await Subscription.find_one(Subscription.stripe_subscription_id == sub_id)
    if existing:
        existing.status = stripe_sub.get("status", existing.status)
        existing.tier = tier
        existing.current_period_start = (
            datetime.fromtimestamp(period_start, tz=timezone.utc)
            if period_start else existing.current_period_start
        )
        existing.current_period_end = (
            datetime.fromtimestamp(period_end, tz=timezone.utc)
            if period_end else existing.current_period_end
        )
        existing.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end"))
        existing.trial_ends_at = (
            datetime.fromtimestamp(trial_end, tz=timezone.utc) if trial_end else None
        )
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
        return existing
    return await Subscription(
        user_id=user_id,
        stripe_customer_id=customer_id or stripe_sub.get("customer", ""),
        stripe_subscription_id=sub_id,
        tier=tier,
        status=stripe_sub.get("status", "active"),
        current_period_start=(
            datetime.fromtimestamp(period_start, tz=timezone.utc) if period_start else None
        ),
        current_period_end=(
            datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None
        ),
        cancel_at_period_end=bool(stripe_sub.get("cancel_at_period_end")),
        trial_ends_at=(
            datetime.fromtimestamp(trial_end, tz=timezone.utc) if trial_end else None
        ),
    ).insert()


async def _handle_checkout_completed(data: dict, request: Optional[Request] = None) -> None:
    """Handle completed checkout — upgrade user tier and record payment."""
    session_id = data.get("id")
    metadata = data.get("metadata", {})
    tier = metadata.get("tier", "")
    user_id = metadata.get("user_id", "")
    customer_id = data.get("customer")

    # Update payment record
    payment = await Payment.find_one(Payment.stripe_session_id == session_id)
    if payment:
        payment.status = "completed"
        await payment.save()
    elif user_id:
        payment = Payment(
            user_id=user_id,
            tier=tier,
            amount=data.get("amount_total", 0),
            currency=data.get("currency", "eur"),
            stripe_session_id=session_id,
            status="completed",
        )
        await payment.insert()

    # Upgrade user tier
    if user_id:
        user = await User.find_one(User.clerk_user_id == user_id)
        if user and TIER_ORDER.get(tier, 0) > TIER_ORDER.get(user.tier, 0):
            old_tier = user.tier
            user.tier = tier
            if customer_id:
                user.stripe_customer_id = customer_id
            await user.save()
            logger.info(f"User {user.email} upgraded: {old_tier} → {tier}")

            await audit.log(
                action=AuditAction.BILLING_SUBSCRIPTION_CREATED,
                user_id=user.clerk_user_id,
                user_email=user.email,
                target_type="user",
                target_id=user.clerk_user_id,
                metadata={"tier": tier, "old_tier": old_tier, "session_id": session_id},
                ip=request.client.host if request and request.client else None,
            )

            # Resume any paused jobs for this user
            proj_id = metadata.get("project_id")
            if proj_id:
                from ..services.token_service import resume_job
                resume_job(proj_id)
        elif user and customer_id and not user.stripe_customer_id:
            # Attach the customer ID even on no-op upgrades
            user.stripe_customer_id = customer_id
            await user.save()

    # If this is a subscription checkout, fetch and persist the subscription
    if data.get("mode") == "subscription" and data.get("subscription"):
        try:
            stripe_sub = stripe.Subscription.retrieve(data["subscription"])
            await _upsert_subscription_from_stripe(
                user_id=user_id, stripe_sub=stripe_sub, customer_id=customer_id,
            )
        except Exception as e:
            logger.warning(f"Could not retrieve subscription after checkout: {e}")

    logger.info(f"Payment completed: session={session_id} tier={tier}")


async def _handle_subscription_created(data: dict) -> None:
    """Handle customer.subscription.created — insert Subscription row."""
    user_id = data.get("metadata", {}).get("user_id", "")
    if not user_id:
        user = await User.find_one(User.stripe_customer_id == data.get("customer", ""))
        if user:
            user_id = user.clerk_user_id
    sub = await _upsert_subscription_from_stripe(user_id=user_id, stripe_sub=data)
    if sub:
        logger.info(f"Subscription created: {sub.stripe_subscription_id} user={user_id} tier={sub.tier}")


async def _handle_subscription_updated(data: dict) -> None:
    """Handle subscription updates — re-upsert and sync user tier if needed."""
    user_id = data.get("metadata", {}).get("user_id", "")
    if not user_id:
        user = await User.find_one(User.stripe_customer_id == data.get("customer", ""))
        if user:
            user_id = user.clerk_user_id
    sub = await _upsert_subscription_from_stripe(user_id=user_id, stripe_sub=data)
    if not sub:
        return
    # If subscription has a new tier, sync to the user
    new_tier = sub.tier
    if new_tier and user_id:
        user = await User.find_one(User.clerk_user_id == user_id)
        if user and TIER_ORDER.get(new_tier, 0) > TIER_ORDER.get(user.tier, 0):
            user.tier = new_tier
            await user.save()
            logger.info(f"User {user.email} tier synced to {new_tier} via subscription.updated")
    logger.info(f"Subscription updated: {sub.stripe_subscription_id} status={sub.status}")


async def _handle_subscription_ended(data: dict) -> None:
    """Handle subscription deletion / pause — mark subscription as canceled
    and (optionally) revert user tier to free if no other active subscription."""
    customer_id = data.get("customer")
    sub_id = data.get("id")

    if sub_id:
        sub = await Subscription.find_one(Subscription.stripe_subscription_id == sub_id)
        if sub:
            sub.status = "canceled"
            sub.canceled_at = datetime.now(timezone.utc)
            await sub.save()

    if customer_id:
        user = await User.find_one(User.stripe_customer_id == customer_id)
        if user:
            # Check if the user has another active sub
            other_active = await Subscription.find_one(
                Subscription.user_id == user.clerk_user_id,
                Subscription.stripe_subscription_id != sub_id,
                In(Subscription.status, ["active", "trialing"]),
            )
            if not other_active and user.tier != "free":
                logger.warning(
                    f"All subscriptions ended for {user.email} (tier was {user.tier}) — keeping current tier until manual review"
                )


async def _handle_invoice_paid(data: dict) -> None:
    """invoice.paid — record successful recurring payment."""
    customer_id = data.get("customer")
    amount = data.get("amount_paid", 0)
    invoice_id = data.get("id")
    if not customer_id:
        return
    user = await User.find_one(User.stripe_customer_id == customer_id)
    if not user:
        return
    await Payment(
        user_id=user.clerk_user_id,
        tier=user.tier,
        amount=amount,
        currency=data.get("currency", "eur"),
        stripe_session_id=invoice_id,  # reuse the field for the invoice id
        status="completed",
    ).insert()
    await audit.log(
        action=AuditAction.BILLING_PAYMENT_SUCCESS,
        user_id=user.clerk_user_id,
        user_email=user.email,
        target_type="invoice",
        target_id=invoice_id,
        metadata={"amount": amount, "currency": data.get("currency", "eur")},
    )
    logger.info(f"Invoice paid: user={user.email} amount={amount}")


async def _handle_invoice_failed(data: dict) -> None:
    """invoice.payment_failed — record and alert (dunning handled by Stripe)."""
    customer_id = data.get("customer")
    invoice_id = data.get("id")
    if not customer_id:
        return
    user = await User.find_one(User.stripe_customer_id == customer_id)
    if not user:
        return
    await audit.log(
        action=AuditAction.BILLING_PAYMENT_FAILED,
        user_id=user.clerk_user_id,
        user_email=user.email,
        target_type="invoice",
        target_id=invoice_id,
        metadata={
            "amount": data.get("amount_due", 0),
            "currency": data.get("currency", "eur"),
        },
    )
    logger.warning(f"Invoice payment failed: user={user.email} invoice={invoice_id}")
