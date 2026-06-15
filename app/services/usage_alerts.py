"""Usage Alerts — TASK-049.

Sends email/Slack notifications when users cross usage thresholds:
  - 80% (soft limit): warning email
  - 100% (hard limit): block notification with upgrade CTA

Respects per-metric cooldown to avoid spamming (max 1 alert per
metric per user per day).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, date
from typing import Optional

from ..config import settings
from ..database import User
from .email_service import send_email, EmailMessage

logger = logging.getLogger(__name__)

# ── In-memory alert cooldown tracker ────────────────────
# Key: f"{user_id}:{metric}:{threshold}"  (threshold = "soft" | "hard")
# Value: date string (YYYY-MM-DD) when last alerted
_alert_cooldowns: dict[str, str] = {}

# Max one alert per metric per day
ALERT_COOLDOWN_DAYS = 1


def _cooldown_key(user_id: str, metric: str, threshold: str) -> str:
    return f"{user_id}:{metric}:{threshold}"


def _check_cooldown(key: str) -> bool:
    """Return True if we should send (not in cooldown)."""
    today = date.today().isoformat()
    last_alert = _alert_cooldowns.get(key)
    if last_alert == today:
        return False
    _alert_cooldowns[key] = today
    return True


# ── Alert Templates ────────────────────────────────────

def _soft_limit_email(
    user_name: str,
    metric: str,
    current: float,
    soft_cap: float,
) -> EmailMessage:
    """Build soft limit warning email."""
    metric_label = metric.replace("_", " ").title()
    pct = round((current / soft_cap) * 100, 1)

    text = (
        f"Hi {user_name or 'there'},\n\n"
        f"You've used {pct}% of your {metric_label} for this month "
        f"({current:.0f} / {soft_cap:.0f}).\n\n"
        f"Upgrade your plan to avoid hitting the hard limit:\n"
        f"{settings.APP_NAME} Dashboard → Settings → Plan & Limits\n\n"
        f"— The {settings.APP_NAME} team"
    )
    html = f"""\
<html><body style="font-family: system-ui, sans-serif; line-height: 1.6; color: #1e293b;">
<div style="max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 20px; color: #f59e0b;">⚠️ Usage Warning</h1>
  <p>You've used <strong>{pct}%</strong> of your <strong>{metric_label}</strong> for this month.</p>
  <div style="background: #fef3c7; border-radius: 8px; padding: 16px; margin: 16px 0;">
    <p style="margin: 0; font-size: 24px; font-weight: 700;">{current:.0f} / {soft_cap:.0f}</p>
    <p style="margin: 4px 0 0; font-size: 13px; color: #92400e;">{metric_label}</p>
  </div>
  <p>Consider <a href="/settings" style="color: #6366f1;">upgrading your plan</a> to increase your limits.</p>
  <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
  <p style="font-size: 12px; color: #94a3b8;">— The {settings.APP_NAME} team</p>
</div>
</body></html>"""

    return EmailMessage(
        to="",  # set by caller
        subject=f"⚠️ Usage Warning — {metric_label} at {pct}%",
        text=text,
        html=html,
    )


def _hard_limit_email(
    user_name: str,
    metric: str,
    current: float,
    hard_cap: float,
) -> EmailMessage:
    """Build hard limit block notification with upgrade CTA."""
    metric_label = metric.replace("_", " ").title()

    text = (
        f"Hi {user_name or 'there'},\n\n"
        f"You've reached the hard limit for {metric_label} "
        f"({current:.0f} / {hard_cap:.0f}).\n\n"
        f"This feature has been temporarily blocked. "
        f"Upgrade your plan to continue:\n"
        f"{settings.APP_NAME} Dashboard → Settings → Plan & Limits\n\n"
        f"— The {settings.APP_NAME} team"
    )
    html = f"""\
<html><body style="font-family: system-ui, sans-serif; line-height: 1.6; color: #1e293b;">
<div style="max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 20px; color: #ef4444;">🚫 Usage Limit Reached</h1>
  <p>You've reached the hard limit for <strong>{metric_label}</strong>.</p>
  <div style="background: #fef2f2; border-radius: 8px; padding: 16px; margin: 16px 0;">
    <p style="margin: 0; font-size: 24px; font-weight: 700;">{current:.0f} / {hard_cap:.0f}</p>
    <p style="margin: 4px 0 0; font-size: 13px; color: #991b1b;">{metric_label} — blocked</p>
  </div>
  <p style="margin: 16px 0;">
    <a href="/settings"
       style="display: inline-block; padding: 12px 24px; background: #6366f1; color: white;
              text-decoration: none; border-radius: 8px; font-weight: 600;">
      Upgrade My Plan →
    </a>
  </p>
  <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
  <p style="font-size: 12px; color: #94a3b8;">— The {settings.APP_NAME} team</p>
</div>
</body></html>"""

    return EmailMessage(
        to="",  # set by caller
        subject=f"🚫 {metric_label} Blocked — Upgrade to Continue",
        text=text,
        html=html,
    )


# ── Public API ─────────────────────────────────────────

async def check_and_alert(
    user: User,
    metric: str,
    current: float,
    soft_cap: Optional[float],
    hard_cap: Optional[float],
) -> dict:
    """Check usage against thresholds and send alerts if needed.

    Returns dict with alert status:
      {"alerted": "none" | "soft" | "hard",
       "blocked": bool, "threshold": float}

    Args:
        user: The user (for email and name).
        metric: Metric name (e.g. "research_call").
        current: Current usage value.
        soft_cap: Soft limit value (None if no soft cap).
        hard_cap: Hard limit value (None if no hard cap).
    """
    result = {
        "alerted": "none",
        "blocked": False,
        "threshold": 0.0,
    }

    if not user.email:
        return result

    # Check hard cap first
    if hard_cap is not None and current >= hard_cap:
        result["blocked"] = True
        result["threshold"] = hard_cap
        key = _cooldown_key(user.clerk_user_id, metric, "hard")
        if _check_cooldown(key):
            try:
                msg = _hard_limit_email(
                    user_name=user.name or "",
                    metric=metric,
                    current=current,
                    hard_cap=hard_cap,
                )
                msg.to = user.email
                await send_email(msg)
                logger.info(
                    f"Hard limit alert sent: user={user.clerk_user_id[:12]} "
                    f"metric={metric} current={current} cap={hard_cap}"
                )
                result["alerted"] = "hard"
            except Exception as e:
                logger.warning(f"Hard limit email failed: {e}")
        return result

    # Check soft cap
    if soft_cap is not None and current >= soft_cap:
        result["threshold"] = soft_cap
        key = _cooldown_key(user.clerk_user_id, metric, "soft")
        if _check_cooldown(key):
            try:
                msg = _soft_limit_email(
                    user_name=user.name or "",
                    metric=metric,
                    current=current,
                    soft_cap=soft_cap,
                )
                msg.to = user.email
                await send_email(msg)
                logger.info(
                    f"Soft limit alert sent: user={user.clerk_user_id[:12]} "
                    f"metric={metric} current={current} cap={soft_cap}"
                )
                result["alerted"] = "soft"
            except Exception as e:
                logger.warning(f"Soft limit email failed: {e}")
        return result

    return result


def get_alert_cooldowns() -> dict:
    """Get current alert cooldowns (for debugging/monitoring)."""
    return dict(_alert_cooldowns)
