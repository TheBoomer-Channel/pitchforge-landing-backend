"""CSP violation report endpoint — receives browser-side Content-Security-Policy
violations via `report-uri /api/v1/csp-report`.

Per spec: the browser POSTs `application/csp-report` or `application/reports+json`
with a JSON body describing the violation. We log it and (in the future) push to
Sentry / a SIEM for security monitoring.

This is a low-noise, high-signal signal of attempted XSS, so it should be
sampled in production (the endpoint never blocks; no auth required).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/csp-report", tags=["security"])


@router.post("")
@router.post("/")
async def csp_report(request: Request):
    """Accept a Content-Security-Policy violation report.

    Accepts both legacy `application/csp-report` and modern
    `application/reports+json` envelopes. Never returns data to the client.
    """
    try:
        body: Any = await request.json()
    except Exception:
        # Some browsers send `{}`; just record a synthetic event
        body = {}

    # Modern envelope: { "reports": [ { "type": "csp-violation", ... } ] }
    reports: list[dict] = []
    if isinstance(body, dict) and "reports" in body and isinstance(body["reports"], list):
        reports = body["reports"]
    # Legacy envelope: { "csp-report": { ... } }
    elif isinstance(body, dict) and "csp-report" in body and isinstance(body["csp-report"], dict):
        reports = [body["csp-report"]]
    elif isinstance(body, dict):
        reports = [body]

    ts = datetime.now(timezone.utc).isoformat()
    for r in reports:
        # Log structured so an aggregator can parse
        logger.warning(
            "csp_violation",
            extra={
                "ts": ts,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "report": r,
            },
        )
    # 204 No Content
    return Response(status_code=204)
