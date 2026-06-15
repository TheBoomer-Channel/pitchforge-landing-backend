"""Webhook dispatcher — HMAC-SHA256 signing + async dispatch with retry (TASK-043).

Call dispatch_webhooks(event_type, payload) from anywhere in the app.
It finds all active endpoints subscribed to the event and fires them.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone

from .models import WebhookEndpoint, WebhookDelivery

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────

MAX_RETRIES = 2
REQUEST_TIMEOUT = 10  # seconds


# ═══════════════════════════════════════════════════════
# HMAC-SHA256 Signing
# ═══════════════════════════════════════════════════════

def sign_payload(payload: dict, secret: str, timestamp: str) -> str:
    """Create HMAC-SHA256 signature of the payload.

    The signing format follows the standard webhook pattern:
       signature = HMAC-SHA256(secret, timestamp + "." + JSON(payload))

    Receivers verify by:
       expected = HMAC-SHA256(secret, t + "." + body)
       hmac.compare_digest(received_sig, expected)
    """
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)
    signed_data = f"{timestamp}.{body}"
    return hmac.new(
        secret.encode("utf-8"),
        signed_data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ═══════════════════════════════════════════════════════
# Dispatch
# ═══════════════════════════════════════════════════════

async def dispatch_webhooks(event_type: str, payload: dict) -> int:
    """Find all active endpoints subscribed to `event_type` and fire webhooks.

    Returns the number of endpoints dispatched to.
    Delivers async without blocking the caller (fire-and-forget with retry).
    """
    endpoints = await WebhookEndpoint.find(
        WebhookEndpoint.is_active == True,
        WebhookEndpoint.events == event_type,
    ).to_list()

    if not endpoints:
        return 0

    # Fire all in parallel (each with its own retry)
    tasks = [_deliver_with_retry(ep, event_type, payload) for ep in endpoints]
    # Don't await — fire and forget (webhooks are async by nature)
    asyncio.create_task(_deliver_all(tasks))

    return len(endpoints)


async def _deliver_all(tasks: list):
    """Gather all delivery tasks, logging failures but never raising."""
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error(f"Webhook dispatch task {i} failed: {r}")


async def _deliver_with_retry(
    endpoint: WebhookEndpoint,
    event_type: str,
    payload: dict,
) -> None:
    """Deliver a webhook to a single endpoint with up to MAX_RETRIES attempts."""
    import httpx

    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = sign_payload(payload, endpoint.secret, timestamp)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PitchForge-Webhook/1.0",
        "X-PitchForge-Event": event_type,
        "X-PitchForge-Signature": f"sha256={signature}",
        "X-PitchForge-Timestamp": timestamp,
        "X-PitchForge-Delivery": "",  # Will be set per attempt
    }

    body_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):  # 1 initial + 2 retries = 3 total
        delivery = WebhookDelivery(
            endpoint_id=endpoint.id,
            event_type=event_type,
            payload=payload,
            attempt=attempt,
            status="pending",
        )
        await delivery.insert()

        headers["X-PitchForge-Delivery"] = delivery.id
        start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.post(endpoint.url, content=body_bytes, headers=headers)

            elapsed = int((__import__("time").monotonic() - start) * 1000)

            delivery.status = "success" if 200 <= resp.status_code < 300 else "failed"
            delivery.response_status = resp.status_code
            delivery.response_body = resp.text[:1000]
            delivery.duration_ms = elapsed
            await delivery.save()

            if delivery.status == "success":
                # Update endpoint stats
                endpoint.last_triggered_at = datetime.now(timezone.utc)
                endpoint.delivery_count += 1
                await endpoint.save()
                return
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(
                    f"Webhook delivery failed (attempt {attempt}): "
                    f"endpoint={endpoint.id} url={endpoint.url} {last_error}"
                )

        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            delivery.status = "failed"
            delivery.error = str(e)[:500]
            delivery.duration_ms = elapsed
            await delivery.save()
            last_error = str(e)
            logger.warning(
                f"Webhook delivery error (attempt {attempt}): "
                f"endpoint={endpoint.id} url={endpoint.url} {e}"
            )

        # Exponential backoff before retry (1s, 2s, 4s...)
        if attempt <= MAX_RETRIES:
            await asyncio.sleep(2 ** (attempt - 1))

    # All attempts exhausted
    endpoint.failure_count += 1
    await endpoint.save()
    logger.error(
        f"Webhook delivery exhausted all retries: "
        f"endpoint={endpoint.id} url={endpoint.url} event={event_type} "
        f"last_error={last_error}"
    )
