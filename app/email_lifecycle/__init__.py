"""Email lifecycle module — TASK-040.

Provides:
  * 5 lifecycle email templates (welcome, first_project, activation,
    upgrade_prompt, winback) with unsubscribe tokens
  * Resend webhook handler (open/click/delivery tracking)
  * One-click unsubscribe (GDPR compliant)
  * Email preferences CRUD
"""

from .models import EmailEvent, UnsubscribeToken
from .templates import (
    send_welcome_email,
    send_first_project_email,
    send_activation_email,
    send_upgrade_prompt_email,
    send_winback_email,
    consume_unsubscribe_token,
    get_or_create_unsubscribe_token,
)
from .routes import router

__all__ = [
    "EmailEvent",
    "UnsubscribeToken",
    "send_welcome_email",
    "send_first_project_email",
    "send_activation_email",
    "send_upgrade_prompt_email",
    "send_winback_email",
    "consume_unsubscribe_token",
    "get_or_create_unsubscribe_token",
    "router",
]
