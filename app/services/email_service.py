"""Email service — TASK-022.

Lightweight email-sending wrapper. In production uses Resend or SMTP;
in dev/test it logs the email to the console with a `console_url` so
the developer can click the verification link.

Configuration (env vars):
  EMAIL_TRANSPORT        "smtp" | "resend" | "log"  (default: "log")
  EMAIL_FROM             "PitchForge <[email protected]>"
  RESEND_API_KEY         (when transport=resend)
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_TLS  (when transport=smtp)
  EMAIL_DRY_RUN          "true"  → never actually send, always log
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    to: str
    subject: str
    text: str
    html: Optional[str] = None


@dataclass
class EmailSendResult:
    ok: bool
    transport: str
    error: Optional[str] = None
    message_id: Optional[str] = None
    # In dev/log mode, contains the verification link so the dev can click it
    console_url: Optional[str] = None


def generate_verification_token() -> tuple[str, str]:
    """Return (plaintext_token, sha256_hash).

    The plaintext is what we put in the URL; the hash is what we store
    in the DB. The plaintext never persists.
    """
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, token_hash


def hash_verification_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Transport implementations ──────────────────────────


async def _send_resend(msg: EmailMessage) -> EmailSendResult:
    """Send via Resend HTTP API."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return EmailSendResult(ok=False, transport="resend", error="RESEND_API_KEY not set")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": os.getenv("EMAIL_FROM", "PitchForge <[email protected]>"),
                    "to": [msg.to],
                    "subject": msg.subject,
                    "text": msg.text,
                    **({"html": msg.html} if msg.html else {}),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return EmailSendResult(ok=True, transport="resend", message_id=data.get("id"))
    except Exception as e:
        return EmailSendResult(ok=False, transport="resend", error=str(e))


def _send_smtp(msg: EmailMessage) -> EmailSendResult:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_TLS", "true").lower() == "true"

    if not host:
        return EmailSendResult(ok=False, transport="smtp", error="SMTP_HOST not set")

    try:
        em = EmailMessage()
        em["From"] = os.getenv("EMAIL_FROM", "PitchForge <[email protected]>")
        em["To"] = msg.to
        em["Subject"] = msg.subject
        em.set_content(msg.text)
        if msg.html:
            em.add_alternative(msg.html, subtype="html")

        with smtplib.SMTP(host, port, timeout=10) as s:
            if use_tls:
                s.starttls()
            if user and password:
                s.login(user, password)
            s.send_message(em)
        return EmailSendResult(ok=True, transport="smtp")
    except Exception as e:
        return EmailSendResult(ok=False, transport="smtp", error=str(e))


def _send_log(msg: EmailMessage) -> EmailSendResult:
    """Dev transport: print to logs."""
    logger.info(
        f"[email:log] to={msg.to} subject={msg.subject!r}\n{msg.text}\n---",
    )
    return EmailSendResult(ok=True, transport="log", message_id="log-" + secrets.token_hex(8))


# ── Public API ─────────────────────────────────────────


async def send_email(msg: EmailMessage) -> EmailSendResult:
    """Send an email using the configured transport.

    Honors `EMAIL_DRY_RUN=true` (always uses log transport).
    """
    if os.getenv("EMAIL_DRY_RUN", "").lower() == "true":
        return _send_log(msg)

    transport = os.getenv("EMAIL_TRANSPORT", "log").lower()
    if transport == "resend":
        return await _send_resend(msg)
    if transport == "smtp":
        return _send_smtp(msg)
    return _send_log(msg)


# ── Templates ───────────────────────────────────────────


def render_verification_email(verification_url: str, lang: str = "en") -> EmailMessage:
    """Build the verification email content for the given language."""
    # Minimal: one language for now (en). Localized templates can be added
    # by loading from content/emails/{lang}/verify.md in a future iteration.
    subject = "Verify your email — PitchForge"

    text = (
        "Welcome to PitchForge!\n\n"
        "Please confirm your email address by clicking the link below.\n"
        "It expires in 24 hours.\n\n"
        f"{verification_url}\n\n"
        "If you didn't sign up for PitchForge, you can safely ignore this email.\n\n"
        "— The PitchForge team\n"
        "CARGOFFER INVESTMENTS SRL — [email protected]"
    )

    html = f"""\
<html><body style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #1e293b;">
<div style="max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 22px; color: #6366f1;">Welcome to PitchForge</h1>
  <p>Please confirm your email address by clicking the button below.</p>
  <p style="margin: 32px 0;">
    <a href="{verification_url}"
       style="display: inline-block; padding: 12px 24px; background: #6366f1; color: white;
              text-decoration: none; border-radius: 8px; font-weight: 600;">
      Verify my email
    </a>
  </p>
  <p style="font-size: 13px; color: #64748b;">This link expires in 24 hours.</p>
  <p style="font-size: 13px; color: #64748b;">
    Or copy this URL into your browser:<br>
    <code style="word-break: break-all;">{verification_url}</code>
  </p>
  <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0;" />
  <p style="font-size: 12px; color: #94a3b8;">
    If you didn't sign up, you can safely ignore this email.<br>
    CARGOFFER INVESTMENTS SRL — [email protected]
  </p>
</div>
</body></html>"""

    return EmailMessage(
        to="",  # set by caller
        subject=subject,
        text=text,
        html=html,
    )
