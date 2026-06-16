"""Waitlist Service — subscribes users to ListMonk newsletter.

Connects the landing page waitlist form to a self-hosted ListMonk instance.
Supports HTTP Basic Auth with API user credentials.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── ListMonk Configuration ─────────────────────────────
# Credentials loaded from environment variables (set in Coolify / .env)

LISTMONK_URL = os.getenv("LISTMONK_URL", "https://newsletter.transcend.cargoffer.com")
LISTMONK_API_USER = os.getenv("LISTMONK_API_USER", "Hermes")
LISTMONK_API_TOKEN = os.getenv("LISTMONK_API_TOKEN", "sWQSkEmQsZr6ezAro0YDAHXYMHiHSeM1")
LISTMONK_LIST_ID = int(os.getenv("LISTMONK_LIST_ID", "3"))  # Pitch-Forge list


async def subscribe(email: str, name: str = "", api_user: str = "", api_token: str = "", list_id: int = 0) -> dict:
    """Subscribe a user to the ListMonk waitlist.

    Args:
        email: Subscriber email address.
        name: Optional subscriber name.
        api_user: ListMonk API username.
        api_token: ListMonk API token.
        list_id: ListMonk list ID to subscribe to.

    Returns:
        dict with success status, message, and optional subscriber data.
    """
    username = api_user or LISTMONK_API_USER
    token = api_token or LISTMONK_API_TOKEN
    target_list = list_id or LISTMONK_LIST_ID

    if not username or not token:
        return {"success": False, "message": "ListMonk not configured — missing API credentials"}

    payload = {
        "email": email,
        "name": name or email.split("@")[0],
        "status": "enabled",
        "lists": [target_list],
        "preconfirm_subscriptions": True,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{LISTMONK_URL}/api/subscribers",
                json=payload,
                auth=(username, token),
                headers={"Content-Type": "application/json"},
            )

            if resp.status_code == 200 or resp.status_code == 201:
                data = resp.json()
                logger.info(f"Waitlist signup: {email} → list {target_list}")
                return {
                    "success": True,
                    "message": "Subscribed successfully!",
                    "data": data.get("data", {}),
                }
            elif resp.status_code == 400:
                # Could be duplicate or validation error
                body = resp.json()
                err_msg = body.get("message", "")
                if "already" in err_msg.lower() or "exists" in err_msg.lower():
                    # Already subscribed — that's fine
                    logger.info(f"Waitlist: {email} already subscribed")
                    return {"success": True, "message": "Already subscribed!"}
                logger.warning(f"ListMonk 400: {err_msg}")
                return {"success": False, "message": err_msg}
            else:
                body = resp.json()
                logger.error(f"ListMonk error {resp.status_code}: {body}")
                return {
                    "success": False,
                    "message": body.get("message", f"API error: {resp.status_code}"),
                }

    except httpx.TimeoutException:
        logger.error("ListMonk request timed out")
        return {"success": False, "message": "Request timed out. Please try again."}
    except Exception as e:
        logger.error(f"ListMonk request failed: {e}")
        return {"success": False, "message": str(e)}
