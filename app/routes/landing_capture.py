"""Landing Capture Routes — backends for contact form and survey submissions on generated landing pages.

Each landing page formula injects forms that POST to these endpoints:
- contact:  POST /api/contact/submit  → forwards to email + stores in DB
- survey:   POST /api/survey/submit   → stores feedback + optional email notification
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

logger = logging.getLogger(__name__)

router = APIRouter(tags=["landing"])


# ── Models ──────────────────────────────────────────────

class ContactSubmitRequest(BaseModel):
    name: str = ""
    email: str
    message: str
    to: str = ""
    """Forward-to email address — from the landing page config."""
    project: str = ""
    """Project slug for tracking."""


class SurveySubmitRequest(BaseModel):
    feedback: str
    email: str = ""
    project: str = ""


# ── Routes ──────────────────────────────────────────────

@router.post("/api/contact/submit")
async def submit_contact(req: ContactSubmitRequest):
    """Receive contact form submissions from generated landing pages.

    Stores the submission in DB and optionally forwards via email.
    The landing page's formula config determines forwarding behavior.
    """
    if not req.email or not req.message:
        raise HTTPException(status_code=400, detail="Email and message are required")

    logger.info(f"Contact submission from {req.email} (project={req.project})")

    # Store in database if available
    submission_id = ""
    try:
        from ..database import ContactSubmission

        submission = ContactSubmission(
            name=req.name,
            email=req.email,
            message=req.message,
            forward_to=req.to,
            project=req.project,
        )
        await submission.insert()
        submission_id = str(submission.id)
        logger.info(f"Contact submission stored: {submission_id}")
    except Exception as e:
        logger.warning(f"Failed to store contact submission: {e}")

    # Forward via email (Resend / SMTP) if configured
    if req.to:
        try:
            await _forward_contact_email(req)
        except Exception as e:
            logger.warning(f"Email forwarding failed (non-fatal): {e}")

    return {
        "success": True,
        "message": "Message received. We'll get back to you soon!",
        "id": submission_id,
    }


@router.post("/api/survey/submit")
async def submit_survey(req: SurveySubmitRequest):
    """Receive survey/feedback submissions from generated landing pages.

    Stores feedback for product research and analysis.
    """
    if not req.feedback:
        raise HTTPException(status_code=400, detail="Feedback is required")

    logger.info(f"Survey submission (project={req.project}, email={req.email or 'anonymous'})")

    # Store in database if available
    submission_id = ""
    try:
        from ..database import SurveySubmission

        submission = SurveySubmission(
            feedback=req.feedback,
            email=req.email,
            project=req.project,
        )
        await submission.insert()
        submission_id = str(submission.id)
        logger.info(f"Survey stored: {submission_id}")
    except Exception as e:
        logger.warning(f"Failed to store survey (may not be critical): {e}")
        submission_id = f"mem-{datetime.utcnow().timestamp():.0f}"

    return {
        "success": True,
        "message": "Thank you for your feedback!",
        "id": submission_id,
    }


# ── Email Forwarding ────────────────────────────────────

async def _forward_contact_email(req: ContactSubmitRequest) -> None:
    """Forward a contact form submission via Resend or SMTP.

    Falls back gracefully if email service is not configured.
    """
    try:
        from ..config import settings

        if settings.RESEND_API_KEY:
            import httpx

            html_body = f"""
            <h2>New Contact Form Submission</h2>
            <p><strong>From:</strong> {req.name or 'Anonymous'} ({req.email})</p>
            <p><strong>Project:</strong> {req.project or 'N/A'}</p>
            <hr>
            <p>{req.message}</p>
            """

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": "contact@pitch-forge.com",
                        "to": [req.to],
                        "subject": f"New Contact: {req.project or 'Landing Page'}",
                        "html": html_body,
                    },
                )
                if resp.status_code == 200:
                    logger.info(f"Contact forwarded via Resend to {req.to}")
                else:
                    logger.warning(f"Resend forwarding failed: {resp.text[:200]}")
        else:
            logger.info(f"RESEND_API_KEY not configured — contact logged only for {req.to}")
    except Exception as e:
        logger.warning(f"Email forwarding error: {e}")
