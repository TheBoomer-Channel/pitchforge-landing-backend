"""Email lifecycle templates — TASK-040.

HTML email templates for the 5 lifecycle emails, plus helpers for
unsubscribe tokens and Resend sending.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta

from ..services.email_service import send_email, EmailMessage
from .models import EmailEvent, UnsubscribeToken

logger = logging.getLogger(__name__)

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5174")


# ── Unsubscribe token helpers ──────────────────────────


def _generate_unsubscribe_token(user_id: str) -> tuple[str, str]:
    """Generate a new unsubscribe token and store its hash in DB.

    Returns the plaintext token for use in email links.
    """
    plaintext = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, token_hash


async def get_or_create_unsubscribe_token(user_id: str) -> str:
    """Get an active unsubscribe token for the user, or create one.

    Returns the plaintext token for use in URLs.
    """
    # Look for an existing active token
    existing = await UnsubscribeToken.find_one(
        UnsubscribeToken.user_id == user_id,
        UnsubscribeToken.status == "active",
        UnsubscribeToken.expires_at > datetime.now(timezone.utc),
    )
    if existing:
        # We can't recover the plaintext (we store the hash), so generate a new one
        # but first consume the old one
        existing.status = "consumed"
        existing.consumed_at = datetime.now(timezone.utc)
        await existing.save()

    plaintext, token_hash = _generate_unsubscribe_token(user_id)
    ut = UnsubscribeToken(
        user_id=user_id,
        token_hash=token_hash,
    )
    await ut.insert()
    return plaintext


async def consume_unsubscribe_token(token: str) -> str | None:
    """Validate and consume an unsubscribe token. Returns user_id or None."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    ut = await UnsubscribeToken.find_one(
        UnsubscribeToken.token_hash == token_hash,
        UnsubscribeToken.status == "active",
    )
    if not ut:
        return None
    if ut.expires_at < datetime.now(timezone.utc):
        ut.status = "expired"
        await ut.save()
        return None

    ut.status = "consumed"
    ut.consumed_at = datetime.now(timezone.utc)
    await ut.save()
    return ut.user_id


# ── Template renderers ─────────────────────────────────


async def send_welcome_email(
    user_id: str, to_email: str, name: str = ""
) -> EmailEvent:
    """Send the Welcome email after signup + trial start."""
    unsub_token = await get_or_create_unsubscribe_token(user_id)
    unsub_url = f"{PUBLIC_BASE_URL}/unsubscribe?token={unsub_token}"
    display_name = name or "there"

    subject = "Welcome to PitchForge — your 14-day Pro trial is active"

    text = (
        f"Hi {display_name},\n\n"
        "Your 14-day Pro trial is now active. You have full access to every feature "
        "for the next 14 days — no credit card needed.\n\n"
        "Here's what to try first:\n"
        "  1. Run a deep research on a startup idea (Research page)\n"
        "  2. Generate a full PRD, financial model, and tech spec (Planning)\n"
        "  3. Spin up a working MVP (CodeGen)\n\n"
        f"Start now: {PUBLIC_BASE_URL}/dashboard\n\n"
        "If you have any questions, just reply to this email.\n\n"
        "— The PitchForge team\n"
        "CARGOFFER INVESTMENTS SRL\n\n"
        f"Unsubscribe: {unsub_url}"
    )

    html = _welcome_html(display_name, unsub_url)

    event = EmailEvent(
        user_id=user_id,
        to_email=to_email,
        email_type="welcome",
        subject=subject,
        status="pending",
    )
    await event.insert()

    msg = EmailMessage(to=to_email, subject=subject, text=text, html=html)
    result = await send_email(msg)

    event.resend_id = result.message_id
    event.status = "sent" if result.ok else "failed"
    event.error = result.error
    await event.save()

    if not result.ok:
        logger.error(f"Welcome email failed: {result.error} for {to_email}")

    return event


async def send_first_project_email(
    user_id: str, to_email: str, name: str = "", project_title: str = ""
) -> EmailEvent:
    """Send when the user creates their first project."""
    unsub_token = await get_or_create_unsubscribe_token(user_id)
    unsub_url = f"{PUBLIC_BASE_URL}/unsubscribe?token={unsub_token}"
    display_name = name or "there"
    proj = project_title or "your startup idea"

    subject = f"You created \"{proj}\" — here's what's next"

    text = (
        f"Hi {display_name},\n\n"
        f"You just created \"{proj}\" — your first project on PitchForge. "
        "That's a big step.\n\n"
        "Your recommended next move:\n"
        "Run a Deep Research on your idea. It takes ~3 minutes and gives you "
        "a competitive analysis, market sizing, risk assessment, and actionable "
        "recommendations.\n\n"
        f"Get started: {PUBLIC_BASE_URL}/dashboard\n\n"
        "— The PitchForge team\n"
        "CARGOFFER INVESTMENTS SRL\n\n"
        f"Unsubscribe: {unsub_url}"
    )

    html = _first_project_html(display_name, proj, unsub_url)

    event = EmailEvent(
        user_id=user_id,
        to_email=to_email,
        email_type="first_project",
        subject=subject,
        status="pending",
    )
    await event.insert()

    msg = EmailMessage(to=to_email, subject=subject, text=text, html=html)
    result = await send_email(msg)

    event.resend_id = result.message_id
    event.status = "sent" if result.ok else "failed"
    event.error = result.error
    await event.save()

    return event


async def send_activation_email(
    user_id: str, to_email: str, name: str = "", days_active: int = 3
) -> EmailEvent:
    """Send an activation/engagement email after N days of active use."""
    unsub_token = await get_or_create_unsubscribe_token(user_id)
    unsub_url = f"{PUBLIC_BASE_URL}/unsubscribe?token={unsub_token}"
    display_name = name or "there"

    subject = "You're on a roll — keep building with PitchForge"

    text = (
        f"Hi {display_name},\n\n"
        f"You've been using PitchForge for {days_active} days now. We noticed "
        "you've been actively researching and building — and we love seeing that.\n\n"
        "Power-user tips:\n"
        "  • Competitive analysis: Run research against specific competitors\n"
        "  • Financial models: Generate 3-year projections with TAM/SAM/SOM\n"
        "  • CodeGen: Turn your PRD into a working MVP in minutes\n\n"
        f"Open your dashboard: {PUBLIC_BASE_URL}/dashboard\n\n"
        "— The PitchForge team\n"
        "CARGOFFER INVESTMENTS SRL\n\n"
        f"Unsubscribe: {unsub_url}"
    )

    html = _activation_html(display_name, days_active, unsub_url)

    event = EmailEvent(
        user_id=user_id,
        to_email=to_email,
        email_type="activation",
        subject=subject,
        status="pending",
    )
    await event.insert()

    msg = EmailMessage(to=to_email, subject=subject, text=text, html=html)
    result = await send_email(msg)

    event.resend_id = result.message_id
    event.status = "sent" if result.ok else "failed"
    event.error = result.error
    await event.save()

    return event


async def send_upgrade_prompt_email(
    user_id: str, to_email: str, name: str = "", days_left: int = 3
) -> EmailEvent:
    """Send an upgrade prompt when the trial is ending soon."""
    unsub_token = await get_or_create_unsubscribe_token(user_id)
    unsub_url = f"{PUBLIC_BASE_URL}/unsubscribe?token={unsub_token}"
    display_name = name or "there"

    if days_left == 1:
        subject = "Last day of your PitchForge Pro trial — upgrade now"
    elif days_left == 0:
        subject = "Your PitchForge Pro trial ends today"
    else:
        subject = f"{days_left} days left of your PitchForge Pro trial"

    text = (
        f"Hi {display_name},\n\n"
        f"Your 14-day Pro trial is wrapping up. We'd love for you to stay.\n\n"
        "Pro features:\n"
        "  • Deep Research — multi-source competitive analysis\n"
        "  • PRD Generator — professional docs with financials\n"
        "  • CodeGen MVP — production-ready code in minutes\n"
        "  • Pitch Deck — investor-ready slides\n\n"
        "Plans start at €9/month with a 30-day money-back guarantee.\n\n"
        f"Upgrade now: {PUBLIC_BASE_URL}/settings\n\n"
        "If you want to stay on the free tier, no action is needed.\n\n"
        "— The PitchForge team\n"
        "CARGOFFER INVESTMENTS SRL\n\n"
        f"Unsubscribe: {unsub_url}"
    )

    html = _upgrade_prompt_html(display_name, days_left, unsub_url)

    event = EmailEvent(
        user_id=user_id,
        to_email=to_email,
        email_type="upgrade_prompt",
        subject=subject,
        status="pending",
    )
    await event.insert()

    msg = EmailMessage(to=to_email, subject=subject, text=text, html=html)
    result = await send_email(msg)

    event.resend_id = result.message_id
    event.status = "sent" if result.ok else "failed"
    event.error = result.error
    await event.save()

    return event


async def send_winback_email(
    user_id: str, to_email: str, name: str = "", days_since_expiry: int = 14
) -> EmailEvent:
    """Send a win-back email after trial expiry + inactivity."""
    unsub_token = await get_or_create_unsubscribe_token(user_id)
    unsub_url = f"{PUBLIC_BASE_URL}/unsubscribe?token={unsub_token}"
    display_name = name or "there"

    subject = "We miss you at PitchForge — come back with 1 month free"

    text = (
        f"Hi {display_name},\n\n"
        f"It's been {days_since_expiry} days since your Pro trial ended. "
        "We hope you've been making progress on your startup idea.\n\n"
        "🎁 Special offer: Come back and get 1 month of Pro free.\n"
        "Use code WELCOMEBACK at checkout. No strings attached.\n\n"
        "What's new:\n"
        "  • Competitive analysis 2.0 — AI-powered SWOT + positioning maps\n"
        "  • Pitch deck generator — investor-ready slides\n"
        "  • CodeGen improvements — faster, better TypeScript support\n\n"
        f"Reactivate: {PUBLIC_BASE_URL}/settings\n\n"
        "— The PitchForge team\n"
        "CARGOFFER INVESTMENTS SRL\n\n"
        f"Unsubscribe: {unsub_url}"
    )

    html = _winback_html(display_name, days_since_expiry, unsub_url)

    event = EmailEvent(
        user_id=user_id,
        to_email=to_email,
        email_type="winback",
        subject=subject,
        status="pending",
    )
    await event.insert()

    msg = EmailMessage(to=to_email, subject=subject, text=text, html=html)
    result = await send_email(msg)

    event.resend_id = result.message_id
    event.status = "sent" if result.ok else "failed"
    event.error = result.error
    await event.save()

    return event


# ── Inline HTML templates ──────────────────────────────
# (Mirrors the React Email templates; rendered server-side for simplicity)


def _email_wrapper(content: str, unsub_url: str = "") -> str:
    """Wrap content in the standard PitchForge email layout."""
    footer = (
        f'<hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">'
        f'<p style="font-size:12px;color:#94a3b8;text-align:center;margin:0 0 4px">'
        f'PitchForge by CARGOFFER INVESTMENTS SRL · '
        f'<a href="{unsub_url}" style="color:#64748b;text-decoration:underline">Unsubscribe</a>'
        f'</p>'
    ) if unsub_url else ""

    return f"""<!DOCTYPE html>
<html><body style="background:#f8fafc;font-family:system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;padding:16px">
<div style="max-width:560px;margin:0 auto;padding:32px 24px;background:#fff;border-radius:12px;border:1px solid #e2e8f0">
  <p style="font-size:24px;font-weight:700;color:#6366f1;margin:0 0 24px;text-align:center">⚒️ PitchForge</p>
  {content}
  {footer}
</div>
</body></html>"""


def _welcome_html(name: str, unsub_url: str) -> str:
    content = f"""
<h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 16px;line-height:1.3">Welcome to PitchForge, {name}!</h1>
<p style="font-size:15px;line-height:1.6;color:#475569;margin:0 0 16px">Your 14-day Pro trial is now active. You have full access to every feature — no credit card required.</p>
<div style="background:#f1f5f9;border-radius:8px;padding:20px;margin:24px 0">
  <h2 style="font-size:16px;font-weight:600;color:#334155;margin:0 0 16px">Here's what to try first</h2>
  <table cellpadding="0" cellspacing="0" style="margin-bottom:16px"><tr>
    <td style="width:36px;vertical-align:top"><span style="display:inline-block;width:28px;height:28px;border-radius:50%;background:#6366f1;color:#fff;font-size:13px;font-weight:700;text-align:center;line-height:28px">1</span></td>
    <td style="vertical-align:top;padding-left:8px"><p style="font-size:14px;font-weight:600;color:#1e293b;margin:0 0 4px">Run a deep research</p><p style="font-size:13px;line-height:1.5;color:#64748b;margin:0">Paste your startup idea and get a multi-source competitive analysis with market sizing, risks, and opportunities.</p></td>
  </tr></table>
  <table cellpadding="0" cellspacing="0" style="margin-bottom:16px"><tr>
    <td style="width:36px;vertical-align:top"><span style="display:inline-block;width:28px;height:28px;border-radius:50%;background:#6366f1;color:#fff;font-size:13px;font-weight:700;text-align:center;line-height:28px">2</span></td>
    <td style="vertical-align:top;padding-left:8px"><p style="font-size:14px;font-weight:600;color:#1e293b;margin:0 0 4px">Generate a full PRD + financial model</p><p style="font-size:13px;line-height:1.5;color:#64748b;margin:0">From the research, create a professional Product Requirements Document, financial projections, and technical architecture.</p></td>
  </tr></table>
  <table cellpadding="0" cellspacing="0"><tr>
    <td style="width:36px;vertical-align:top"><span style="display:inline-block;width:28px;height:28px;border-radius:50%;background:#6366f1;color:#fff;font-size:13px;font-weight:700;text-align:center;line-height:28px">3</span></td>
    <td style="vertical-align:top;padding-left:8px"><p style="font-size:14px;font-weight:600;color:#1e293b;margin:0 0 4px">Spin up a working MVP</p><p style="font-size:13px;line-height:1.5;color:#64748b;margin:0">Generate a complete codebase with frontend, backend, and deployment config — ready to ship.</p></td>
  </tr></table>
</div>
<div style="text-align:center;margin:32px 0 24px">
  <a href="{PUBLIC_BASE_URL}/dashboard" style="display:inline-block;padding:12px 28px;background:#6366f1;border-radius:8px;color:#fff;font-size:15px;font-weight:600;text-decoration:none">Start your first project →</a>
</div>
"""
    return _email_wrapper(content, unsub_url)


def _first_project_html(name: str, project_title: str, unsub_url: str) -> str:
    content = f"""
<h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 16px;line-height:1.3">Nice work, {name}!</h1>
<p style="font-size:15px;line-height:1.6;color:#475569;margin:0 0 12px">You just created <strong>{project_title}</strong> — your first project on PitchForge. That's a big step.</p>
<p style="font-size:15px;line-height:1.6;color:#475569;margin:0 0 12px">Here's your recommended next move:</p>
<div style="background:#eef2ff;border-radius:8px;padding:20px;margin:24px 0">
  <p style="font-size:13px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:0.05em;margin:0 0 8px">💡 Next step</p>
  <p style="font-size:14px;line-height:1.6;color:#334155;margin:0 0 16px">Run a <strong>Deep Research</strong> on your idea. It takes ~3 minutes and gives you a competitive analysis, market sizing, risk assessment, and actionable recommendations — all from real data sources.</p>
  <a href="{PUBLIC_BASE_URL}/dashboard" style="display:inline-block;padding:12px 28px;background:#6366f1;border-radius:8px;color:#fff;font-size:15px;font-weight:600;text-decoration:none">Research your idea →</a>
</div>
"""
    return _email_wrapper(content, unsub_url)


def _activation_html(name: str, days_active: int, unsub_url: str) -> str:
    content = f"""
<h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 16px;line-height:1.3">You're on a roll, {name}!</h1>
<p style="font-size:15px;line-height:1.6;color:#475569;margin:0 0 12px">You've been using PitchForge for {days_active} days now. We noticed you've been actively researching and building — and we love seeing that.</p>
<div style="margin:24px 0;text-align:center">
  <table cellpadding="0" cellspacing="0" style="margin:0 auto"><tr>
    <td style="width:150px;padding:16px 12px;background:#f1f5f9;border-radius:8px;text-align:center;margin:0 8px">
      <p style="font-size:28px;font-weight:700;color:#6366f1;margin:0 0 4px">{days_active}</p>
      <p style="font-size:12px;color:#64748b;font-weight:500;text-transform:uppercase;margin:0">Days active</p>
    </td>
    <td style="width:20px"></td>
    <td style="width:150px;padding:16px 12px;background:#f1f5f9;border-radius:8px;text-align:center">
      <p style="font-size:28px;font-weight:700;color:#6366f1;margin:0 0 4px">Pro</p>
      <p style="font-size:12px;color:#64748b;font-weight:500;text-transform:uppercase;margin:0">Your plan</p>
    </td>
    <td style="width:20px"></td>
    <td style="width:150px;padding:16px 12px;background:#f1f5f9;border-radius:8px;text-align:center">
      <p style="font-size:28px;font-weight:700;color:#6366f1;margin:0 0 4px">∞</p>
      <p style="font-size:12px;color:#64748b;font-weight:500;text-transform:uppercase;margin:0">Potential</p>
    </td>
  </tr></table>
</div>
<div style="background:#f8fafc;border-radius:8px;padding:16px 20px;margin:16px 0">
  <p style="font-size:14px;line-height:1.6;color:#334155;margin:0 0 10px">🎯 <strong>Competitive analysis</strong> — Run research against specific competitors to see where you can differentiate.</p>
  <p style="font-size:14px;line-height:1.6;color:#334155;margin:0 0 10px">📊 <strong>Financial models</strong> — Generate 3-year projections with TAM/SAM/SOM breakdowns.</p>
  <p style="font-size:14px;line-height:1.6;color:#334155;margin:0">⚡ <strong>CodeGen</strong> — Turn your PRD into a working MVP in minutes, not weeks.</p>
</div>
<div style="text-align:center;margin:28px 0 24px">
  <a href="{PUBLIC_BASE_URL}/dashboard" style="display:inline-block;padding:12px 28px;background:#6366f1;border-radius:8px;color:#fff;font-size:15px;font-weight:600;text-decoration:none">Open your dashboard →</a>
</div>
"""
    return _email_wrapper(content, unsub_url)


def _upgrade_prompt_html(name: str, days_left: int, unsub_url: str) -> str:
    headline = (
        "Last call: your Pro trial ends tomorrow"
        if days_left == 1
        else f"{days_left} days left of your Pro trial"
    )

    content = f"""
<h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 16px;line-height:1.3">{headline}</h1>
<p style="font-size:15px;line-height:1.6;color:#475569;margin:0 0 12px">Hey {name} — your 14-day Pro trial is wrapping up. We'd love for you to stay.</p>
<div style="margin:24px 0">
  <table cellpadding="0" cellspacing="0"><tr>
    <td style="width:48%;padding:12px 8px 8px 0;vertical-align:top"><p style="font-size:20px;margin:0 0 4px">🔬</p><p style="font-size:14px;font-weight:600;color:#1e293b;margin:0 0 4px">Deep Research</p><p style="font-size:12px;line-height:1.5;color:#64748b;margin:0">Multi-source competitive analysis, market sizing, and risk assessment.</p></td>
    <td style="width:48%;padding:12px 8px 8px 0;vertical-align:top"><p style="font-size:20px;margin:0 0 4px">📋</p><p style="font-size:14px;font-weight:600;color:#1e293b;margin:0 0 4px">PRD Generator</p><p style="font-size:12px;line-height:1.5;color:#64748b;margin:0">Professional product requirements with financials and tech specs.</p></td>
  </tr></table>
  <table cellpadding="0" cellspacing="0"><tr>
    <td style="width:48%;padding:12px 8px 8px 0;vertical-align:top"><p style="font-size:20px;margin:0 0 4px">⚡</p><p style="font-size:14px;font-weight:600;color:#1e293b;margin:0 0 4px">CodeGen MVP</p><p style="font-size:12px;line-height:1.5;color:#64748b;margin:0">Production-ready codebases generated from your PRD in minutes.</p></td>
    <td style="width:48%;padding:12px 8px 8px 0;vertical-align:top"><p style="font-size:20px;margin:0 0 4px">🎨</p><p style="font-size:14px;font-weight:600;color:#1e293b;margin:0 0 4px">Pitch Deck</p><p style="font-size:12px;line-height:1.5;color:#64748b;margin:0">Investor-ready slides with narrative, visuals, and financial charts.</p></td>
  </tr></table>
</div>
<div style="background:#eef2ff;border-radius:12px;padding:28px 24px;margin:24px 0;text-align:center;border:2px solid #6366f1">
  <p style="font-size:13px;font-weight:600;color:#6366f1;text-transform:uppercase;letter-spacing:0.05em;margin:0 0 4px">Plans start at</p>
  <p style="font-size:42px;font-weight:800;color:#1e293b;margin:0;line-height:1">€9</p>
  <p style="font-size:15px;color:#64748b;margin:0 0 12px">/month</p>
  <p style="font-size:12px;color:#6366f1;margin:0 0 20px;font-style:italic">30-day money-back guarantee, no questions asked</p>
  <a href="{PUBLIC_BASE_URL}/settings" style="display:inline-block;padding:14px 32px;background:#6366f1;border-radius:8px;color:#fff;font-size:16px;font-weight:700;text-decoration:none">Upgrade to Pro →</a>
</div>
<p style="font-size:15px;line-height:1.6;color:#475569;margin:0">If you want to keep using the free tier, no action is needed — your account will automatically switch to Free when the trial ends.</p>
"""
    return _email_wrapper(content, unsub_url)


def _winback_html(name: str, days_since_expiry: int, unsub_url: str) -> str:
    content = f"""
<h1 style="font-size:22px;font-weight:700;color:#1e293b;margin:0 0 16px;line-height:1.3">We miss you, {name}</h1>
<p style="font-size:15px;line-height:1.6;color:#475569;margin:0 0 12px">It's been {days_since_expiry} days since your Pro trial ended. We hope you've been making progress on your startup idea — and we'd love to help you take it further.</p>
<div style="background:#fef3c7;border-radius:12px;padding:28px 24px;margin:24px 0;text-align:center;border:2px solid #f59e0b">
  <p style="font-size:13px;font-weight:700;color:#b45309;text-transform:uppercase;letter-spacing:0.05em;margin:0 0 8px">🎁 Special offer</p>
  <h2 style="font-size:20px;font-weight:700;color:#1e293b;margin:0 0 12px;line-height:1.3">Come back and get 1 month of Pro free</h2>
  <p style="font-size:14px;line-height:1.6;color:#475569;margin:0 0 20px">Use code <strong>WELCOMEBACK</strong> at checkout for your first month on us. No strings attached — cancel anytime.</p>
  <a href="{PUBLIC_BASE_URL}/settings" style="display:inline-block;padding:14px 32px;background:#6366f1;border-radius:8px;color:#fff;font-size:16px;font-weight:700;text-decoration:none">Reactivate Pro →</a>
</div>
<div style="background:#f1f5f9;border-radius:8px;padding:20px;margin:16px 0 24px">
  <p style="font-size:14px;font-weight:700;color:#334155;margin:0 0 12px">🆕 What's new on PitchForge</p>
  <p style="font-size:14px;line-height:1.6;color:#475569;margin:0 0 8px">• <strong>Competitive analysis 2.0</strong> — now with AI-powered SWOT and positioning maps</p>
  <p style="font-size:14px;line-height:1.6;color:#475569;margin:0 0 8px">• <strong>Pitch deck generator</strong> — investor-ready slides in minutes</p>
  <p style="font-size:14px;line-height:1.6;color:#475569;margin:0">• <strong>CodeGen improvements</strong> — faster builds, better TypeScript support</p>
</div>
"""
    return _email_wrapper(content, unsub_url)
