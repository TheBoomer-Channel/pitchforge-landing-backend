"""Marketplace Template model — TASK-053.

Users publish templates (pitch, landing, pricing) → review → published → purchase → 70/30 split.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import BaseModel, Field


class TemplateReview(BaseModel):
    """Review record for a template."""
    reviewer_id: str  # Clerk user ID of moderator
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision: str  # approved / rejected
    notes: Optional[str] = None


class Template(Document):
    """A published template in the marketplace.

    Templates are created from generated assets (landing, pitch deck, pricing).
    Authors submit → moderators review → published → users purchase.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_id: Indexed(str)  # Clerk user ID of the author
    author_name: Optional[str] = None

    # Type & metadata
    template_type: str  # landing / pitch / pricing
    title: str
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    # The actual content (HTML)
    content: str  # The generated HTML

    # Preview data (structured, for React landing page)
    preview_data: Optional[dict] = None  # LandingData-compatible JSON

    # Cover / preview image
    cover_image_url: Optional[str] = None

    # Pricing
    price_cents: int = 0  # Price in USD cents (e.g., 999 = $9.99)
    currency: str = "usd"

    # Status workflow
    status: str = "draft"  # draft → pending_review → approved → rejected → published
    review: Optional[TemplateReview] = None

    # Analytics
    downloads: int = 0
    purchases: int = 0
    revenue_cents: int = 0  # Total revenue in cents (author's share)
    featured: bool = False  # Pinned on marketplace

    # Stripe Connect
    stripe_account_id: Optional[str] = None  # Author's Stripe Connect Express account ID
    stripe_price_id: Optional[str] = None  # Stripe Price ID for this template

    # SEO
    slug: Optional[Indexed(str, unique=True)] = None  # URL-friendly slug
    meta_description: Optional[str] = None
    seo_keywords: list[str] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    class Settings:
        name = "marketplace_templates"
        indexes = [
            "author_id",
            "status",
            "template_type",
            [("status", 1), ("featured", -1), ("created_at", -1)],
            [("slug", 1)],
            [("template_type", 1), ("status", 1), ("created_at", -1)],
        ]


class TemplatePurchase(Document):
    """Record of a template purchase — for revenue tracking and access control."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    template_id: Indexed(str)
    buyer_id: str  # Clerk user ID
    buyer_email: Optional[str] = None
    amount_cents: int = 0
    platform_fee_cents: int = 0  # 30% take-rate
    author_share_cents: int = 0  # 70% to author
    currency: str = "usd"
    status: str = "completed"  # pending / completed / refunded
    stripe_session_id: Optional[str] = None
    stripe_transfer_id: Optional[str] = None  # Payout to author
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "marketplace_purchases"
        indexes = [
            "template_id",
            "buyer_id",
            [("buyer_id", 1), ("created_at", -1)],
        ]


# ── API Schemas ──────────────────────────────────────

class PublishTemplateRequest(BaseModel):
    template_type: str
    title: str
    description: Optional[str] = None
    content: str
    preview_data: Optional[dict] = None
    cover_image_url: Optional[str] = None
    price_cents: int = 0  # Free if 0
    tags: list[str] = Field(default_factory=list)
    meta_description: Optional[str] = None
    seo_keywords: list[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    decision: str  # approved / rejected
    notes: Optional[str] = None


class TemplateListResponse(BaseModel):
    templates: list[dict]
    total: int
    page: int
    page_size: int
