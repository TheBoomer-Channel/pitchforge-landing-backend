"""Coupon & discount routes — validate, apply, manage.

Supports:
- Admin CRUD for coupons (list, create, update, delete)
- Public validation endpoint (frontend hint)
- Stripe checkout integration: apply coupon to Stripe session via discounts[]
- Redemption tracking per user
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..auth import get_current_user, require_tier, TIER_ORDER
from ..config import settings
from ..database import User, Payment
from ..models.audit import AuditAction
from ..models.coupon import Coupon, Redemption
from ..pricing import PRICE_MAP, AMOUNT_MAP
from ..services.audit_service import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/coupons", tags=["coupons"])


# ── Schemas ────────────────────────────────────────────

class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=30, description="Coupon code")
    kind: str = Field(..., pattern=r"^(percent|amount)$")
    value: int = Field(..., ge=1, description="Percent (1-100) or amount in cents")
    max_uses: int = Field(0, ge=0, description="0 = unlimited")
    valid_from: Optional[str] = None  # ISO datetime
    valid_until: Optional[str] = None  # ISO datetime
    plan_restriction: Optional[str] = Field(None, pattern=r"^(starter|pro|code_mvp)?$")
    partner_id: Optional[str] = None


class CouponUpdate(BaseModel):
    max_uses: Optional[int] = None
    valid_until: Optional[str] = None
    is_active: Optional[bool] = None
    plan_restriction: Optional[str] = None
    partner_id: Optional[str] = None


class CouponValidateRequest(BaseModel):
    code: str
    tier: str


class CouponValidateResponse(BaseModel):
    valid: bool
    reason: str = ""
    coupon: Optional[dict] = None


class ApplyCouponRequest(BaseModel):
    coupon_code: str
    tier: str


class ApplyCouponResponse(BaseModel):
    valid: bool
    reason: str = ""
    coupon: Optional[dict] = None
    checkout_url: Optional[str] = None


# ── Helpers ────────────────────────────────────────────

def _coupon_to_dict(c: Coupon) -> dict:
    return {
        "id": str(c.id),
        "code": c.code,
        "kind": c.kind,
        "value": c.value,
        "max_uses": c.max_uses,
        "used_count": c.used_count,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_until": c.valid_until.isoformat() if c.valid_until else None,
        "plan_restriction": c.plan_restriction,
        "partner_id": c.partner_id,
        "is_active": c.is_active,
        "stripe_coupon_id": c.stripe_coupon_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _compute_discount(kind: str, value: int, tier: str) -> int:
    """Compute the effective discount amount in cents for a given tier."""
    base = AMOUNT_MAP.get(tier, 0)
    if kind == "percent":
        return int(base * min(value, 100) / 100)
    return min(value, base)  # Cannot discount more than the price


async def _sync_stripe_coupon(coupon: Coupon) -> Optional[str]:
    """Create or update a Stripe coupon matching our internal coupon.

    Returns the Stripe coupon ID, or None if Stripe is not configured.
    """
    if not settings.STRIPE_API_KEY:
        return None
    try:
        # Build Stripe coupon params
        params: dict = {
            "id": coupon.code.lower().replace("_", "-"),  # Stripe IDs must be lowercase
            "name": coupon.code,
            "duration": "forever",  # Applies to every recurring payment
        }
        if coupon.kind == "percent":
            params["percent_off"] = min(coupon.value, 100)
        else:
            params["amount_off"] = coupon.value
            params["currency"] = "eur"

        if coupon.valid_until:
            params["redeem_by"] = int(coupon.valid_until.timestamp())

        if coupon.max_uses > 0:
            params["max_redemptions"] = coupon.max_uses

        stripe_coupon = stripe.Coupon.create(**params)
        return stripe_coupon.id
    except Exception as e:
        logger.warning(f"Failed to sync coupon to Stripe: {e}")
        return None


# ── Public endpoints ───────────────────────────────────

@router.post("/validate", response_model=CouponValidateResponse)
async def validate_coupon(body: CouponValidateRequest):
    """Check if a coupon code is valid for a given tier.

    Returns valid=true/false with a human-readable reason.
    This is safe to call from the frontend before checkout.
    """
    code = body.code.upper().strip()
    coupon = await Coupon.find_one(Coupon.code == code)

    if not coupon:
        return CouponValidateResponse(valid=False, reason="Coupon not found")

    valid, reason = await coupon.is_valid()
    if not valid:
        return CouponValidateResponse(valid=False, reason=reason)

    # Check plan restriction
    if coupon.plan_restriction and coupon.plan_restriction != body.tier:
        return CouponValidateResponse(
            valid=False,
            reason=f"This coupon applies to the {coupon.plan_restriction} plan only",
        )

    return CouponValidateResponse(
        valid=True,
        coupon=_coupon_to_dict(coupon),
    )


@router.post("/apply", response_model=ApplyCouponResponse)
async def apply_coupon_to_checkout(
    body: ApplyCouponRequest,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Validate a coupon and create a Stripe checkout session with the discount applied.

    Combines validation + checkout creation in one call.
    Each user may use a given coupon code only once.
    """
    code = body.coupon_code.upper().strip()
    coupon = await Coupon.find_one(Coupon.code == code)

    if not coupon:
        return ApplyCouponResponse(valid=False, reason="Coupon not found")

    # Validate coupon
    valid, reason = await coupon.is_valid()
    if not valid:
        return ApplyCouponResponse(valid=False, reason=reason)

    if coupon.plan_restriction and coupon.plan_restriction != body.tier:
        return ApplyCouponResponse(
            valid=False,
            reason=f"This coupon applies to the {coupon.plan_restriction} plan only",
        )

    # Check if user already used this coupon
    existing = await Redemption.find_one(
        Redemption.coupon_code == code,
        Redemption.user_id == user.clerk_user_id,
    )
    if existing:
        return ApplyCouponResponse(
            valid=False,
            reason="You have already used this coupon",
        )

    # Prevent downgrades
    current_level = TIER_ORDER.get(user.tier, 0)
    requested_level = TIER_ORDER.get(body.tier, 0)
    if requested_level <= current_level:
        return ApplyCouponResponse(
            valid=False,
            reason=f"Cannot downgrade from {user.tier} to {body.tier}",
        )

    if not settings.STRIPE_API_KEY:
        return ApplyCouponResponse(
            valid=False,
            reason="Stripe is not configured",
        )

    price_id = PRICE_MAP.get(body.tier)
    if not price_id:
        return ApplyCouponResponse(
            valid=False,
            reason=f"Price not configured for tier: {body.tier}",
        )

    # Compute discount for display
    discount_amount = _compute_discount(coupon.kind, coupon.value, body.tier)
    discount_label = f"{coupon.value}%" if coupon.kind == "percent" else f"€{coupon.value / 100:.2f} off"

    try:
        # Build checkout session with discount
        session_params: dict = {
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "payment" if body.tier == "code_mvp" else "subscription",
            "success_url": str(request.base_url) + "dashboard?checkout=success",
            "cancel_url": str(request.base_url) + "dashboard?checkout=cancel",
            "metadata": {
                "user_id": str(user.clerk_user_id),
                "tier": body.tier,
                "coupon_code": code,
            },
        }

        # Apply the Stripe coupon if synced, otherwise pass discounts as a coupon object
        if coupon.stripe_coupon_id:
            session_params["discounts"] = [{"coupon": coupon.stripe_coupon_id}]
        else:
            # Create an inline discount
            discount_params: dict = {}
            if coupon.kind == "percent":
                discount_params["percent_off"] = min(coupon.value, 100)
            else:
                discount_params["amount_off"] = coupon.value
                discount_params["currency"] = "eur"
            discount_params["duration"] = "forever"
            session_params["discounts"] = [{"coupon_data": discount_params}]

        # Add customer context
        if user.stripe_customer_id:
            session_params["customer"] = user.stripe_customer_id
        else:
            session_params["customer_email"] = user.email

        # Add subscription_data only for recurring modes
        if body.tier != "code_mvp":
            session_params["subscription_data"] = {
                "metadata": {"user_id": str(user.clerk_user_id), "tier": body.tier, "coupon_code": code},
            }

        session = stripe.checkout.Session.create(**session_params)

    except stripe.StripeError as e:
        logger.error(f"Stripe checkout error (coupon): {e}")
        return ApplyCouponResponse(
            valid=False,
            reason="Stripe checkout creation failed",
        )

    # Record the payment attempt
    await Payment(
        user_id=str(user.clerk_user_id),
        tier=body.tier,
        amount=max(0, AMOUNT_MAP.get(body.tier, 0) - discount_amount),
        currency="eur",
        stripe_session_id=session.id,
        status="pending",
    ).insert()

    # Record the redemption
    await Redemption(
        coupon_code=code,
        user_id=user.clerk_user_id,
        tier=body.tier,
        stripe_session_id=session.id,
        stripe_coupon_id=coupon.stripe_coupon_id,
        discount_amount=discount_amount,
    ).insert()

    # Increment coupon usage
    await coupon.increment_use()

    # Audit log
    await audit.log(
        action=AuditAction.BILLING_COUPON_REDEEMED,
        user_id=user.clerk_user_id,
        user_email=user.email,
        target_type="coupon",
        target_id=code,
        metadata={
            "tier": body.tier,
            "discount_label": discount_label,
            "discount_amount": discount_amount,
            "session_id": session.id,
        },
    )

    logger.info(
        f"Coupon applied: user={user.email} code={code} tier={body.tier} "
        f"discount={discount_label}"
    )

    return ApplyCouponResponse(
        valid=True,
        coupon={
            **_coupon_to_dict(coupon),
            "discount_label": discount_label,
            "discount_amount": discount_amount,
            "final_price": max(0, AMOUNT_MAP.get(body.tier, 0) - discount_amount),
        },
        checkout_url=session.url,
    )


# ── Admin endpoints (require pro+ or admin role) ───────

@router.get("/admin", summary="List all coupons (admin)")
async def list_coupons(
    user: User = Depends(require_tier("pro")),
):
    """List all coupons. Requires pro tier or higher."""
    coupons = await Coupon.find_all().sort("-created_at").to_list()
    return {"coupons": [_coupon_to_dict(c) for c in coupons]}


@router.post("/admin", summary="Create a coupon (admin)", status_code=201)
async def create_coupon(
    body: CouponCreate,
    user: User = Depends(require_tier("pro")),
):
    """Create a new coupon. Requires pro tier or higher."""
    code = body.code.upper().strip()

    # Check for duplicate
    existing = await Coupon.find_one(Coupon.code == code)
    if existing:
        raise HTTPException(status_code=409, detail=f"Coupon '{code}' already exists")

    # Parse optional datetime fields
    valid_from = None
    valid_until = None
    if body.valid_from:
        try:
            valid_from = datetime.fromisoformat(body.valid_from)
            if valid_from.tzinfo is None:
                valid_from = valid_from.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid valid_from format (use ISO 8601)")
    if body.valid_until:
        try:
            valid_until = datetime.fromisoformat(body.valid_until)
            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid valid_until format (use ISO 8601)")

    coupon = Coupon(
        code=code,
        kind=body.kind,
        value=body.value,
        max_uses=body.max_uses,
        valid_from=valid_from,
        valid_until=valid_until,
        plan_restriction=body.plan_restriction,
        partner_id=body.partner_id,
    )
    await coupon.insert()

    # Sync to Stripe
    stripe_id = await _sync_stripe_coupon(coupon)
    if stripe_id:
        coupon.stripe_coupon_id = stripe_id
        await coupon.save()
        logger.info(f"Coupon synced to Stripe: {code} → {stripe_id}")

    await audit.log(
        action=AuditAction.BILLING_COUPON_CREATED,
        user_id=user.clerk_user_id,
        user_email=user.email,
        target_type="coupon",
        target_id=code,
        metadata={"kind": body.kind, "value": body.value, "stripe_id": stripe_id},
    )

    logger.info(f"Coupon created: {code} ({body.kind}={body.value})")
    return _coupon_to_dict(coupon)


@router.patch("/admin/{code}", summary="Update a coupon (admin)")
async def update_coupon(
    code: str,
    body: CouponUpdate,
    user: User = Depends(require_tier("pro")),
):
    """Update a coupon's max_uses, valid_until, is_active, etc."""
    coupon_code = code.upper().strip()
    coupon = await Coupon.find_one(Coupon.code == coupon_code)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    update_fields = {}
    if body.max_uses is not None:
        coupon.max_uses = body.max_uses
        update_fields["max_uses"] = body.max_uses
    if body.valid_until is not None:
        try:
            dt = datetime.fromisoformat(body.valid_until)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            coupon.valid_until = dt
            update_fields["valid_until"] = body.valid_until
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid valid_until format")
    if body.is_active is not None:
        coupon.is_active = body.is_active
        update_fields["is_active"] = body.is_active
    if body.plan_restriction is not None:
        coupon.plan_restriction = body.plan_restriction or None
        update_fields["plan_restriction"] = body.plan_restriction
    if body.partner_id is not None:
        coupon.partner_id = body.partner_id or None
        update_fields["partner_id"] = body.partner_id

    coupon.updated_at = datetime.now(timezone.utc)
    await coupon.save()

    await audit.log(
        action=AuditAction.BILLING_COUPON_UPDATED,
        user_id=user.clerk_user_id,
        user_email=user.email,
        target_type="coupon",
        target_id=coupon_code,
        metadata=update_fields,
    )

    return _coupon_to_dict(coupon)


@router.delete("/admin/{code}", summary="Delete a coupon (admin)", status_code=204)
async def delete_coupon(
    code: str,
    user: User = Depends(require_tier("pro")),
):
    """Soft-delete a coupon by setting is_active=false."""
    coupon_code = code.upper().strip()
    coupon = await Coupon.find_one(Coupon.code == coupon_code)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")

    coupon.is_active = False
    coupon.updated_at = datetime.now(timezone.utc)
    await coupon.save()

    await audit.log(
        action=AuditAction.BILLING_COUPON_DELETED,
        user_id=user.clerk_user_id,
        user_email=user.email,
        target_type="coupon",
        target_id=coupon_code,
    )

    logger.info(f"Coupon disabled: {coupon_code}")


@router.get("/redemptions", summary="List coupon redemptions for the current user")
async def list_user_redemptions(
    user: User = Depends(get_current_user),
):
    """List all coupon redemptions by the current user."""
    redemptions = await Redemption.find(
        Redemption.user_id == user.clerk_user_id,
    ).sort("-redeemed_at").to_list()

    return {
        "redemptions": [
            {
                "coupon_code": r.coupon_code,
                "tier": r.tier,
                "discount_amount": r.discount_amount,
                "redeemed_at": r.redeemed_at.isoformat() if r.redeemed_at else None,
            }
            for r in redemptions
        ]
    }
