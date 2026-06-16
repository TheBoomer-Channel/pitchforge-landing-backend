"""Landing Generate Route — unified endpoint for landing page generation and deployment.

Chains: idea → research → generate HTML → deploy to Cloudflare Pages → return URL
Supports modular formulas: waitlist, contact, newsletter, booking, payment
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..generator import generate_landing
from ..research.models import ResearchReport
from ..services.landing_deployer import deploy_landing, _slugify, get_deployer
from ..services.landing_formulas import (
    FormulaConfig,
    FormulaRegistry,
    FormulaType,
)
from ..services.research_runner import run_inline_research
from ..utils.paths import GENERATED_DIR, make_output_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/landing", tags=["landing"])


# ── Request / Response Models ──────────────────────────

class LandingGenerateRequest(BaseModel):
    idea: str
    """The startup idea text to generate a landing page for."""
    formula: str = "waitlist"
    """Capture formula: waitlist, contact, newsletter, booking, payment, survey."""
    target_market: Optional[str] = None
    """Optional target market/industry for research."""
    business_model: Optional[str] = None
    """Optional business model for research."""
    custom_domain: Optional[str] = None
    """Optional custom domain for premium clients."""
    contact_email: Optional[str] = None
    """Email for contact form submissions (used when formula=contact)."""
    stripe_link: Optional[str] = None
    """Stripe payment link (used when formula=payment)."""
    booking_url: Optional[str] = None
    """Booking URL (used when formula=booking)."""


class LandingGenerateResponse(BaseModel):
    success: bool
    idea: str
    slug: str
    formula: str
    url: str
    preview_url: str
    project_id: str
    duration_ms: int
    status: str
    custom_domain: Optional[dict] = None


# ── Routes ─────────────────────────────────────────────

@router.post("/generate", response_model=LandingGenerateResponse)
async def generate_landing_page(req: LandingGenerateRequest):
    """Generate a landing page from an idea and deploy it live.

    This is the main product endpoint: it runs research, generates HTML,
    deploys to Cloudflare Pages, and returns the live URL.

    The formula parameter controls what capture module is included:
    - waitlist:   ListMonk email capture (default)
    - contact:    Contact form with email forwarding
    - newsletter: Double opt-in newsletter
    - booking:    Calendly-style booking embed
    - payment:    Stripe pre-order button
    """
    start_time = datetime.utcnow()
    idea = req.idea.strip()
    if not idea or len(idea) < 10:
        raise HTTPException(status_code=400, detail="Idea must be at least 10 characters")

    slug = _slugify(idea)
    project_id = str(uuid.uuid4())[:12]

    # Validate formula
    try:
        formula_type = FormulaType(req.formula.lower())
    except ValueError:
        valid = [f.value for f in FormulaType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid formula '{req.formula}'. Valid: {', '.join(valid)}",
        )

    logger.info(f"🚀 Generating landing page for '{idea[:60]}' (formula={formula_type.value})")

    # ── Phase 1: Research ──────────────────────────────
    try:
        report = await run_inline_research(
            idea=idea,
            target_market=req.target_market or "",
            business_model=req.business_model or "",
        )
        logger.info(f"✅ Research complete: {len(report.competitors)} competitors, {report.research_duration_ms}ms")
    except Exception as e:
        logger.error(f"Research failed: {e}")
        raise HTTPException(status_code=500, detail=f"Research failed: {e}")

    # ── Phase 2: Generate Landing HTML ─────────────────
    try:
        output_dir = make_output_dir(idea, GENERATED_DIR)
        html = await generate_landing(report, output_dir=output_dir)
        logger.info(f"✅ Landing HTML generated ({len(html)} chars)")
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Landing generation failed: {e}")        # ── Phase 3: Inject Capture Formula ────────────────
    try:
        config = FormulaRegistry.get_default_config(formula_type, project_id)

        # Configure formula-specific settings
        if formula_type == FormulaType.CONTACT and req.contact_email:
            config.contact_email = req.contact_email
        elif formula_type == FormulaType.PAYMENT and req.stripe_link:
            config.stripe_link = req.stripe_link
        elif formula_type == FormulaType.BOOKING and req.booking_url:
            config.booking_url = req.booking_url

        capture_html = FormulaRegistry.get_capture_html(config, slug)

        # Inject capture form before the closing </body> tag
        # Note: capture_html already includes its own <script> with submit functions
        if "</body>" in html:
            html = html.replace("</body>", capture_html + "\n</body>", 1)

        logger.info(f"✅ Capture formula '{formula_type.value}' injected")
    except Exception as e:
        logger.warning(f"Formula injection failed (non-fatal): {e}")

    # ── Phase 4: Deploy to Cloudflare Pages ────────────
    try:
        deploy_result = await deploy_landing(
            html=html,
            idea=idea,
            custom_domain=req.custom_domain,
        )
        logger.info(f"✅ Deployed to {deploy_result['url']}")
    except Exception as e:
        logger.error(f"Deploy failed: {e}")
        raise HTTPException(status_code=500, detail=f"Deploy failed: {e}")

    duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

    return LandingGenerateResponse(
        success=True,
        idea=idea,
        slug=slug,
        formula=formula_type.value,
        url=deploy_result["url"],
        preview_url=deploy_result.get("preview_url", deploy_result["url"]),
        project_id=project_id,
        duration_ms=duration_ms,
        status="live",
        custom_domain=deploy_result.get("custom_domain"),
    )


@router.get("/status/{slug}")
async def get_landing_status(slug: str):
    """Check the deployment status of a landing page by slug."""
    try:
        deployer = get_deployer()
        status = await deployer.get_deployment_status(slug)
        return {"success": True, **status}
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return {"success": False, "slug": slug, "error": str(e)}


@router.post("/custom-domain")
async def link_custom_domain(slug: str = Query(...), domain: str = Query(...)):
    """Link a custom domain to an existing landing page (premium feature)."""
    try:
        deployer = get_deployer()
        result = await deployer.link_custom_domain(slug, domain)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
