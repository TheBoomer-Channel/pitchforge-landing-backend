"""Marketplace API routes — TASK-053.

Endpoints:
  PUBLIC (no auth):
    GET  /api/v1/marketplace/templates        — Browse catalog
    GET  /api/v1/marketplace/templates/{id}   — Template detail
    GET  /api/v1/marketplace/landing-data/{id} — Public landing preview data

  AUTH:
    POST /api/v1/marketplace/templates        — Publish template
    GET  /api/v1/marketplace/my-templates     — Author dashboard
    POST /api/v1/marketplace/{id}/submit      — Submit for review
    POST /api/v1/marketplace/{id}/purchase    — Purchase template

  ADMIN (require_tier("pro")):
    GET  /api/v1/marketplace/review-queue     — Pending reviews
    POST /api/v1/marketplace/review/{id}      — Approve/reject

  STRIPE CONNECT:
    POST /api/v1/marketplace/connect-account  — Create Express account
    GET  /api/v1/marketplace/onboarding-link  — Get onboarding URL
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth import get_current_user, require_tier
from ..config import settings
from ..database import ResearchResult, User
from ..models.marketplace import (
    PublishTemplateRequest,
    ReviewRequest,
    TemplateListResponse,
)
from ..services.marketplace import (
    create_template,
    create_connect_onboarding_link,
    create_stripe_connect_account,
    extract_preview_data_from_report,
    get_author_templates,
    get_review_queue,
    get_template_by_id,
    get_template_by_slug,
    get_user_purchases,
    has_user_purchased,
    list_templates,
    purchase_template,
    review_template,
    submit_for_review,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])


# ═══════════════════════════════════════════════════════════
#  PUBLIC ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/templates", summary="Browse public marketplace templates")
async def browse_templates(
    type: Optional[str] = Query(None, description="Filter by template type: landing, pitch, pricing"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    search: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    sort: str = Query("newest", regex="^(newest|popular|price_low)$"),
) -> dict:
    """Public endpoint — no auth required. Browse published templates in the marketplace."""
    templates, total = await list_templates(
        template_type=type,
        page=page,
        page_size=page_size,
        search=search,
        tag=tag,
        sort=sort,
    )

    return {
        "templates": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "template_type": t.template_type,
                "author_name": t.author_name,
                "price_cents": t.price_cents,
                "currency": t.currency,
                "cover_image_url": t.cover_image_url,
                "tags": t.tags,
                "slug": t.slug,
                "purchases": t.purchases,
                "featured": t.featured,
                "meta_description": t.meta_description,
                "published_at": t.published_at.isoformat() if t.published_at else None,
            }
            for t in templates
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/templates/{identifier}", summary="Get template detail")
async def get_template_detail(identifier: str) -> dict:
    """Public — get a single template by ID or slug. Returns full content if purchased or free."""
    # Try by slug first, then by ID
    template = await get_template_by_slug(identifier)
    if not template:
        template = await get_template_by_id(identifier)

    if not template or template.status != "published":
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "id": template.id,
        "title": template.title,
        "description": template.description,
        "template_type": template.template_type,
        "author_name": template.author_name,
        "price_cents": template.price_cents,
        "currency": template.currency,
        "cover_image_url": template.cover_image_url,
        "tags": template.tags,
        "slug": template.slug,
        "purchases": template.purchases,
        "featured": template.featured,
        "meta_description": template.meta_description,
        "seo_keywords": template.seo_keywords,
        "preview_data": template.preview_data,  # Public preview data
        "has_content": False,  # Full content requires purchase
        "published_at": template.published_at.isoformat() if template.published_at else None,
    }


@router.get("/landing-data/{project_id}", summary="Public landing preview data (SEO)")
async def public_landing_data(project_id: str) -> dict:
    """Public endpoint — no auth required. Returns landing page preview data for SEO.\n\n
    Serves structured LandingData JSON for the React landing preview at /landing/:id.\n
    This data is extracted from a ResearchResult. Only serves projects with completed research.
    """
    result = await ResearchResult.find_one(ResearchResult.project_id == project_id)
    if not result or not result.report_json:
        raise HTTPException(status_code=404, detail="Research data not found")

    report = result.report_json
    preview = extract_preview_data_from_report(report)

    # Add the project ID for tracking
    preview["project_id"] = project_id
    return preview


# ═══════════════════════════════════════════════════════════
#  AUTH ENDPOINTS (Author)
# ═══════════════════════════════════════════════════════════

@router.post("/templates", summary="Publish a new template to the marketplace")
async def publish_template(
    body: PublishTemplateRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Create a new template. First version goes to 'draft' status.\n
    Use POST /{id}/submit to send it for review.
    """
    try:
        template = await create_template(
            author_id=user.clerk_user_id,
            author_name=user.name,
            template_type=body.template_type,
            title=body.title,
            content=body.content,
            price_cents=body.price_cents,
            description=body.description,
            preview_data=body.preview_data,
            cover_image_url=body.cover_image_url,
            tags=body.tags,
            meta_description=body.meta_description,
            seo_keywords=body.seo_keywords,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "id": template.id,
        "slug": template.slug,
        "status": template.status,
        "message": "Template created. Submit for review when ready.",
    }


@router.get("/my-templates", summary="Author's template dashboard")
async def my_templates(
    user: User = Depends(get_current_user),
) -> dict:
    """Get all templates authored by the current user."""
    templates = await get_author_templates(user.clerk_user_id)

    total_revenue = sum(t.revenue_cents for t in templates if t.status == "published")
    total_purchases = sum(t.purchases for t in templates if t.status == "published")

    return {
        "templates": [
            {
                "id": t.id,
                "title": t.title,
                "template_type": t.template_type,
                "status": t.status,
                "price_cents": t.price_cents,
                "purchases": t.purchases,
                "revenue_cents": t.revenue_cents,
                "slug": t.slug,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "published_at": t.published_at.isoformat() if t.published_at else None,
                "has_stripe_account": bool(t.stripe_account_id),
            }
            for t in templates
        ],
        "total": len(templates),
        "total_revenue_cents": total_revenue,
        "total_purchases": total_purchases,
    }


@router.post("/{template_id}/submit", summary="Submit template for review")
async def submit_for_review_endpoint(
    template_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Submit a template to the moderation queue."""
    try:
        template = await submit_for_review(template_id, user.clerk_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not template:
        raise HTTPException(status_code=404, detail="Template not found or not owned by you")

    return {"id": template.id, "status": template.status, "message": "Submitted for review."}


@router.post("/{template_id}/purchase", summary="Purchase a template")
async def purchase_template_endpoint(
    template_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Purchase a template.\n
    If price > 0, creates a Stripe Checkout Session.\n
    If price = 0 (free), records the purchase immediately.
    """
    template = await get_template_by_id(template_id)
    if not template or template.status != "published":
        raise HTTPException(status_code=404, detail="Template not found")

    # Check if already purchased
    already = await has_user_purchased(template_id, user.clerk_user_id)
    if already:
        return {
            "access_granted": True,
            "message": "Already purchased — access granted.",
            "checkout_url": None,
        }

    # Free template → grant immediately
    if template.price_cents <= 0:
        purchase = await purchase_template(
            template_id=template_id,
            buyer_id=user.clerk_user_id,
            buyer_email=user.email,
        )
        if not purchase:
            raise HTTPException(status_code=500, detail="Purchase recording failed")

        return {
            "access_granted": True,
            "message": "Free template — access granted.",
            "checkout_url": None,
        }

    # Paid template → create Stripe Checkout
    if not settings.STRIPE_API_KEY:
        raise HTTPException(status_code=503, detail="Stripe is not configured")

    if not template.stripe_price_id:
        raise HTTPException(status_code=500, detail="Template has no Stripe price configured")

    try:
        import stripe
        stripe.api_key = settings.STRIPE_API_KEY

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": template.stripe_price_id, "quantity": 1}],
            mode="payment",
            success_url=f"{str(request.base_url)}marketplace/{template.slug or template.id}?purchase=success",
            cancel_url=f"{str(request.base_url)}marketplace/{template.slug or template.id}?purchase=cancel",
            metadata={
                "template_id": template_id,
                "buyer_id": user.clerk_user_id,
                "buyer_email": user.email or "",
                "type": "marketplace_purchase",
            },
        )

        return {
            "access_granted": False,
            "checkout_url": session.url,
            "stripe_session_id": session.id,
        }

    except Exception as e:
        logger.error(f"Stripe checkout failed: {e}")
        raise HTTPException(status_code=502, detail="Checkout creation failed")


@router.get("/my-purchases", summary="Get user's purchased templates")
async def my_purchases(
    user: User = Depends(get_current_user),
) -> dict:
    """Get all templates the current user has purchased."""
    purchases = await get_user_purchases(user.clerk_user_id)

    template_ids = [p.template_id for p in purchases]
    templates = []
    for tid in template_ids:
        t = await get_template_by_id(tid)
        if t:
            templates.append({
                "id": t.id,
                "title": t.title,
                "template_type": t.template_type,
                "slug": t.slug,
                "price_cents": t.price_cents,
                "content": t.content,  # Full content — purchased!
                "cover_image_url": t.cover_image_url,
                "purchased_at": next(
                    (p.created_at.isoformat() for p in purchases if p.template_id == tid),
                    None,
                ),
            })

    return {"purchases": templates, "total": len(templates)}


@router.get("/access/{template_id}", summary="Check if user has access to a template")
async def check_access(
    template_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Check if the current user has purchased a specific template."""
    template = await get_template_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Author always has access
    if template.author_id == user.clerk_user_id:
        return {"has_access": True, "is_author": True, "is_purchased": False}

    purchased = await has_user_purchased(template_id, user.clerk_user_id)
    return {"has_access": purchased, "is_author": False, "is_purchased": purchased}


# ═══════════════════════════════════════════════════════════
#  ADMIN / MODERATOR ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.get("/review-queue", summary="Get pending template reviews (admin)")
async def review_queue(
    user: User = Depends(require_tier("pro")),
) -> dict:
    """Get all templates pending moderator review."""
    templates = await get_review_queue()

    return {
        "queue": [
            {
                "id": t.id,
                "title": t.title,
                "template_type": t.template_type,
                "author_name": t.author_name,
                "author_id": t.author_id,
                "price_cents": t.price_cents,
                "description": t.description,
                "slug": t.slug,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in templates
        ],
        "total": len(templates),
    }


@router.post("/review/{template_id}", summary="Approve or reject a template (admin)")
async def review_template_endpoint(
    template_id: str,
    body: ReviewRequest,
    user: User = Depends(require_tier("pro")),
) -> dict:
    """Approve or reject a template. Only moderators/admins can review."""
    try:
        template = await review_template(
            template_id=template_id,
            reviewer_id=user.clerk_user_id,
            decision=body.decision,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "id": template.id,
        "status": template.status,
        "message": f"Template {body.decision}.",
    }


# ═══════════════════════════════════════════════════════════
#  STRIPE CONNECT ENDPOINTS
# ═══════════════════════════════════════════════════════════

@router.post("/connect-account", summary="Create Stripe Connect Express account")
async def connect_account(
    user: User = Depends(get_current_user),
) -> dict:
    """Create a Stripe Connect Express account to receive payouts.\n
    Returns the onboarding URL the user must visit to complete setup.
    """
    account_id = await create_stripe_connect_account(user)
    if not account_id:
        if not settings.STRIPE_API_KEY:
            raise HTTPException(status_code=503, detail="Stripe is not configured")
        raise HTTPException(status_code=500, detail="Failed to create Connect account")

    # Generate onboarding link
    refresh_url = "/settings?connect=failed"
    return_url = "/settings?connect=success"
    onboarding_url = await create_connect_onboarding_link(account_id, refresh_url, return_url)

    return {
        "account_id": account_id,
        "onboarding_url": onboarding_url,
        "message": "Connect account created. Complete onboarding via the URL.",
    }


@router.get("/onboarding-link", summary="Get Stripe Connect onboarding link")
async def onboarding_link(
    user: User = Depends(get_current_user),
) -> dict:
    """Get a new onboarding link for an existing Connect account.\n
    The user must have a stripe_account_id on one of their templates.
    """
    # Find the user's stripe account from their templates
    templates = await get_author_templates(user.clerk_user_id)
    account_id = None
    for t in templates:
        if t.stripe_account_id:
            account_id = t.stripe_account_id
            break

    if not account_id:
        # No account yet — try creating one
        account_id = await create_stripe_connect_account(user)
        if not account_id:
            raise HTTPException(status_code=500, detail="Could not create/create Connect account")

    refresh_url = "/settings?connect=failed"
    return_url = "/settings?connect=success"
    onboarding_url = await create_connect_onboarding_link(account_id, refresh_url, return_url)

    return {"account_id": account_id, "onboarding_url": onboarding_url}
