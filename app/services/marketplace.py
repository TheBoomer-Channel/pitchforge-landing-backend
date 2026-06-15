"""Marketplace service layer — TASK-053.

Business logic for template publishing, review, purchase, and Stripe Connect flows.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from ..database import User
from ..models.marketplace import Template, TemplatePurchase, TemplateReview

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────

PLATFORM_FEE_PCT = 30  # 30% take-rate
AUTHOR_SHARE_PCT = 100 - PLATFORM_FEE_PCT  # 70%

ALLOWED_TYPES = ["landing", "pitch", "pricing"]
ALLOWED_STATUSES = ["draft", "pending_review", "approved", "rejected", "published"]


# ── Slug Generation ────────────────────────────────────

def _slugify(title: str, max_len: int = 60) -> str:
    """Create a URL-safe slug from a title."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len]


async def _ensure_unique_slug(base_slug: str, template_id: Optional[str] = None) -> str:
    """Ensure the slug is unique by appending a counter if needed."""
    slug = base_slug
    counter = 1
    while True:
        existing = await Template.find_one(Template.slug == slug)
        if not existing:
            return slug
        if template_id and existing.id == template_id:
            return slug  # Same template, slug is fine
        slug = f"{base_slug}-{counter}"
        counter += 1


# ── CRUD Operations ────────────────────────────────────

async def create_template(
    author_id: str,
    author_name: Optional[str],
    template_type: str,
    title: str,
    content: str,
    price_cents: int = 0,
    description: Optional[str] = None,
    preview_data: Optional[dict] = None,
    cover_image_url: Optional[str] = None,
    tags: Optional[list[str]] = None,
    meta_description: Optional[str] = None,
    seo_keywords: Optional[list[str]] = None,
) -> Template:
    """Create a new template in draft status.

    Automatically creates Stripe Price if price > 0 and STRIPE_API_KEY is set.
    """
    if template_type not in ALLOWED_TYPES:
        raise ValueError(f"Invalid template type: {template_type}. Must be one of {ALLOWED_TYPES}")

    slug = await _ensure_unique_slug(_slugify(title))

    template = Template(
        author_id=author_id,
        author_name=author_name or "",
        template_type=template_type,
        title=title,
        description=description or "",
        content=content,
        preview_data=preview_data,
        cover_image_url=cover_image_url,
        price_cents=price_cents,
        tags=tags or [],
        meta_description=meta_description or description or "",
        seo_keywords=seo_keywords or [],
        slug=slug,
        status="draft",
    )

    # Create Stripe Price if priced
    if price_cents > 0 and settings.STRIPE_API_KEY:
        try:
            await _create_stripe_price(template)
        except Exception as e:
            logger.warning(f"Failed to create Stripe price for template {template.id}: {e}")

    await template.insert()
    logger.info(f"Template created: {template.id} ({title}) by {author_id}")
    return template


async def submit_for_review(template_id: str, user_id: str) -> Optional[Template]:
    """Submit a template for moderation review."""
    template = await Template.find_one(Template.id == template_id, Template.author_id == user_id)
    if not template:
        return None
    if template.status not in ("draft", "rejected"):
        raise ValueError(f"Cannot submit template in status: {template.status}")

    template.status = "pending_review"
    template.updated_at = datetime.now(timezone.utc)
    await template.save()
    logger.info(f"Template submitted for review: {template.id}")
    return template


async def review_template(
    template_id: str,
    reviewer_id: str,
    decision: str,
    notes: Optional[str] = None,
) -> Optional[Template]:
    """Approve or reject a template (admin/moderator only)."""
    if decision not in ("approved", "rejected"):
        raise ValueError(f"Invalid decision: {decision}")

    template = await Template.find_one(Template.id == template_id)
    if not template:
        return None
    if template.status != "pending_review":
        raise ValueError(f"Template is not pending review: {template.status}")

    template.review = TemplateReview(
        reviewer_id=reviewer_id,
        decision=decision,
        notes=notes,
    )
    template.status = decision  # approved → will be set to 'published'
    template.updated_at = datetime.now(timezone.utc)

    if decision == "approved":
        template.status = "published"
        template.published_at = datetime.now(timezone.utc)

    await template.save()
    logger.info(f"Template {template.id} reviewed: {decision} by {reviewer_id}")
    return template


async def list_templates(
    template_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    sort: str = "newest",
) -> tuple[list[Template], int]:
    """List published templates for the public marketplace."""
    query = {"status": "published"}

    if template_type:
        query["template_type"] = template_type

    filters = []
    if search:
        filters.append({"title": {"$regex": search, "$options": "i"}})
    if tag:
        filters.append({"tags": tag})

    # MongoDB aggregation
    full_query = {"$and": [query] + filters} if filters else query

    sort_field = {"newest": "created_at", "popular": "purchases", "price_low": "price_cents"}.get(sort, "created_at")
    sort_dir = -1 if sort in ("newest", "popular") else 1  # price_low ascending

    total = await Template.find(full_query).count()
    skip = (page - 1) * page_size

    templates = (
        await Template.find(full_query)
        .sort((sort_field, sort_dir))
        .skip(skip)
        .limit(page_size)
        .to_list()
    )

    return templates, total


async def get_template_by_slug(slug: str) -> Optional[Template]:
    """Get a published template by its slug (for public preview)."""
    return await Template.find_one(Template.slug == slug, Template.status == "published")


async def get_template_by_id(template_id: str) -> Optional[Template]:
    """Get any template by ID (for authors/admins)."""
    return await Template.find_one(Template.id == template_id)


async def get_author_templates(author_id: str) -> list[Template]:
    """Get all templates for an author."""
    return await Template.find(Template.author_id == author_id).sort(-Template.created_at).to_list()


async def get_review_queue() -> list[Template]:
    """Get all templates pending review (admin)."""
    return await Template.find(Template.status == "pending_review").sort(-Template.created_at).to_list()


async def purchase_template(
    template_id: str,
    buyer_id: str,
    buyer_email: Optional[str] = None,
    stripe_session_id: Optional[str] = None,
) -> Optional[TemplatePurchase]:
    """Record a template purchase.

    If Stripe is configured and the template has a Stripe price,
    a Stripe Checkout Session should have been created before calling this.
    """
    template = await Template.find_one(Template.id == template_id, Template.status == "published")
    if not template:
        return None

    # Check if user already purchased
    existing = await TemplatePurchase.find_one(
        TemplatePurchase.template_id == template_id,
        TemplatePurchase.buyer_id == buyer_id,
        TemplatePurchase.status == "completed",
    )
    if existing:
        return existing  # Already purchased

    amount_cents = template.price_cents
    platform_fee_cents = int(amount_cents * PLATFORM_FEE_PCT / 100)
    author_share_cents = amount_cents - platform_fee_cents

    purchase = TemplatePurchase(
        template_id=template_id,
        buyer_id=buyer_id,
        buyer_email=buyer_email or "",
        amount_cents=amount_cents,
        platform_fee_cents=platform_fee_cents,
        author_share_cents=author_share_cents,
        stripe_session_id=stripe_session_id,
        status="completed",
    )
    await purchase.insert()

    # Update template stats
    template.purchases += 1
    template.revenue_cents += author_share_cents
    await template.save()

    # If Stripe Connect is set up, trigger the transfer to the author
    if template.stripe_account_id and settings.STRIPE_API_KEY and author_share_cents > 0:
        try:
            from stripe import Transfer
            transfer = Transfer.create(
                amount=author_share_cents,
                currency=template.currency,
                destination=template.stripe_account_id,
                transfer_group=f"template_{template_id}",
                metadata={
                    "template_id": template_id,
                    "purchase_id": purchase.id,
                    "buyer_id": buyer_id,
                },
            )
            purchase.stripe_transfer_id = transfer.id
            await purchase.save()
            logger.info(f"Stripe transfer {transfer.id} for template {template_id}: {author_share_cents}c")
        except Exception as e:
            logger.warning(f"Stripe transfer failed for template {template_id}: {e}")

    logger.info(f"Template purchased: {template_id} by {buyer_id} for {amount_cents}c")
    return purchase


async def get_user_purchases(user_id: str) -> list[TemplatePurchase]:
    """Get all purchases made by a user."""
    return await TemplatePurchase.find(
        TemplatePurchase.buyer_id == user_id,
        TemplatePurchase.status == "completed",
    ).sort(-TemplatePurchase.created_at).to_list()


async def has_user_purchased(template_id: str, user_id: str) -> bool:
    """Check if a user has already purchased a template."""
    purchase = await TemplatePurchase.find_one(
        TemplatePurchase.template_id == template_id,
        TemplatePurchase.buyer_id == user_id,
        TemplatePurchase.status == "completed",
    )
    return purchase is not None


# ── Stripe Connect ─────────────────────────────────────

async def create_stripe_connect_account(user: User) -> Optional[str]:
    """Create a Stripe Connect Express account for a user (author).

    Returns the account ID, or None if Stripe is not configured.
    """
    if not settings.STRIPE_API_KEY:
        return None

    try:
        import stripe
        stripe.api_key = settings.STRIPE_API_KEY

        account = stripe.Account.create(
            type="express",
            country="US",
            email=user.email or "",
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
            metadata={
                "user_id": user.clerk_user_id,
                "app": "pitchforge",
            },
        )
        logger.info(f"Stripe Connect account created: {account.id} for {user.email}")
        return account.id
    except Exception as e:
        logger.error(f"Failed to create Stripe Connect account: {e}")
        return None


async def create_connect_onboarding_link(account_id: str, refresh_url: str, return_url: str) -> Optional[str]:
    """Create an onboarding link for a Stripe Connect Express account.

    Returns the onboarding URL, or None if Stripe is not configured.
    """
    if not settings.STRIPE_API_KEY:
        return None

    try:
        import stripe
        stripe.api_key = settings.STRIPE_API_KEY

        link = stripe.AccountLink.create(
            account=account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding",
        )
        return link.url
    except Exception as e:
        logger.error(f"Failed to create Connect onboarding link: {e}")
        return None


async def _create_stripe_price(template: Template) -> Optional[str]:
    """Create a Stripe Price for a template (for checkout)."""
    if not settings.STRIPE_API_KEY or template.price_cents <= 0:
        return None

    try:
        import stripe
        stripe.api_key = settings.STRIPE_API_KEY

        product = stripe.Product.create(
            name=template.title,
            description=template.description or "",
            metadata={
                "template_id": template.id,
                "template_type": template.template_type,
                "app": "pitchforge_marketplace",
            },
        )

        price = stripe.Price.create(
            product=product.id,
            unit_amount=template.price_cents,
            currency=template.currency,
            metadata={"template_id": template.id},
        )

        template.stripe_price_id = price.id
        return price.id
    except Exception as e:
        logger.warning(f"Failed to create Stripe price: {e}")
        return None


# ── Landing Data Extraction ────────────────────────────

def extract_preview_data_from_report(report_json: dict) -> dict:
    """Extract a LandingData-compatible dict from a ResearchReport JSON.

    This is used to serve public previews at /landing/:id.
    """
    competitors = report_json.get("competitors", [])
    opps = report_json.get("opportunity_gaps", [])
    sizing = report_json.get("market_sizing", {})
    validation = report_json.get("market_validation", {})

    faqs = []
    summary = report_json.get("summary", "")
    if summary:
        faqs.append({
            "question": "What's the big insight?",
            "answer": summary[:200],
        })

    return {
        "idea": report_json.get("idea", "Untitled"),
        "tagline": report_json.get("recommended_positioning", ""),
        "summary": summary,
        "pricing_range": report_json.get("recommended_pricing_range", "Free to get started"),
        "features": report_json.get("recommended_mvp_features", []),
        "competitors": [
            {
                "name": c.get("name", ""),
                "description": c.get("description", ""),
                "strengths": c.get("strengths", []),
                "weaknesses": c.get("weaknesses", []),
                "pain_points": c.get("pain_points", []),
                "pricing": c.get("pricing", ""),
            }
            for c in competitors[:6]
        ],
        "risks": report_json.get("risk_factors", []),
        "opportunity_gaps": [
            {
                "gap": g.get("gap", ""),
                "evidence": g.get("evidence", []),
                "severity": g.get("severity", "medium"),
            }
            for g in opps[:6]
        ],
        "market_sizing": {
            "tam": sizing.get("tam", ""),
            "sam": sizing.get("sam", ""),
            "som": sizing.get("som", ""),
            "growth_rate": sizing.get("growth_rate", ""),
        } if sizing else None,
        "market_validation": {
            "reddit_posts_found": validation.get("reddit_posts_found", 0),
            "hn_mentions": validation.get("hn_mentions", 0),
            "gh_similar_projects": validation.get("gh_similar_projects", 0),
        } if validation else None,
        "faqs": faqs + [
            {"question": "How does pricing work?", "answer": f"{report_json.get('recommended_pricing_range', 'Free')}. No hidden fees."},
            {"question": "Is there an API?", "answer": "Yes, API-first by design."},
        ],
    }
