"""Audit log routes — TASK-014 + TASK-035 (admin only).

  * GET  /api/v1/audit/events                — paginated list with filters (admin)
  * GET  /api/v1/audit/events.csv           — CSV export (admin)
  * GET  /api/v1/audit/events.json          — JSON export (admin)
  * GET  /api/v1/audit/verify-chain         — re-compute hash chain (admin)
  * GET  /api/v1/audit/actions              — list of distinct actions (admin)

Admin gating: a user is admin if their email is in AUDIT_ADMIN_EMAILS.
Rate limit: 1 export (CSV or JSON) per hour per user.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..auth import get_current_user
from ..database import User
from ..models.audit import AuditEvent
from ..services.audit_service import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["admin"])

ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("AUDIT_ADMIN_EMAILS", "[email protected]").split(",")
    if e.strip()
}

# Rate-limit tracking for exports (in-memory; resets on restart)
_export_tracker: dict[str, datetime] = {}


def _check_export_rate_limit(user_email: str) -> None:
    """Raise 429 if user exported within the last hour.
    Also cleans up stale entries older than 2 hours."""
    now = datetime.now(timezone.utc)
    # Cleanup stale entries
    stale_keys = [k for k, v in _export_tracker.items() if (now - v) > timedelta(hours=2)]
    for k in stale_keys:
        del _export_tracker[k]

    key = user_email.lower()
    last = _export_tracker.get(key)
    if last and (now - last) < timedelta(hours=1):
        remaining = timedelta(hours=1) - (now - last)
        minutes = int(remaining.total_seconds() / 60) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit: 1 export per hour. Try again in {minutes} min.",
        )
    _export_tracker[key] = now


def _parse_date(value: str | None, param_name: str) -> datetime | None:
    """Parse ISO date string, raising 422 on invalid input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {param_name}: '{value}'. Use ISO format (YYYY-MM-DD).",
        )


def _build_audit_query(
    user_id: str | None = None,
    action: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Shared query builder for list + export endpoints."""
    q: dict = {}
    if user_id:
        q["user_id"] = user_id
    if action:
        q["action"] = action
    if from_date:
        q["created_at__gte"] = _parse_date(from_date, "from_date")
    if to_date:
        q["created_at__lt"] = _parse_date(to_date, "to_date")
    return q


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Gate audit endpoints to admin users only."""
    if (user.email or "").lower() not in ADMIN_EMAILS:
        raise HTTPException(
            status_code=403,
            detail="Audit endpoints require admin privileges.",
        )
    return user


@router.get("/events", summary="List audit events (paginated, admin)")
async def list_events(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = Query(None, description="Filter by target type"),
    target_id: Optional[str] = Query(None, description="Filter by target ID"),
    from_date: Optional[str] = Query(None, description="ISO date, inclusive"),
    to_date: Optional[str] = Query(None, description="ISO date, exclusive"),
    search: Optional[str] = Query(None, description="Full-text search in user_email and metadata"),
    since_seq: Optional[int] = Query(None, description="Return events with seq > since_seq"),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(require_admin),
) -> dict:
    """Paginated list with advanced filters, ordered by seq desc."""
    q: dict = {}
    if user_id:
        q["user_id"] = user_id
    if action:
        q["action"] = action
    if target_type:
        q["target_type"] = target_type
    if target_id:
        q["target_id"] = target_id
    if since_seq is not None:
        q["seq__gt"] = since_seq
    if from_date:
        q["created_at__gte"] = datetime.fromisoformat(from_date)
    if to_date:
        q["created_at__lt"] = datetime.fromisoformat(to_date)
    if search:
        q["$or"] = [
            {"user_email": {"$regex": search, "$options": "i"}},
            {"action": {"$regex": search, "$options": "i"}},
        ]

    events = await AuditEvent.find(q).sort("-seq").limit(limit).to_list()
    return {
        "events": [
            {
                "seq": e.seq,
                "user_id": e.user_id,
                "user_email": e.user_email,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "ip": e.ip,
                "user_agent": e.user_agent,
                "created_at": e.created_at.isoformat(),
                "metadata": e.metadata,
                "this_hash": e.this_hash,
                "prev_hash": e.prev_hash,
            }
            for e in events
        ],
        "count": len(events),
        "has_more": len(events) == limit,
    }


@router.get("/events.csv", summary="Export audit log as CSV (admin, rate-limited)")
async def export_csv(
    request: Request,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(10_000, ge=1, le=100_000),
    user: User = Depends(require_admin),
) -> StreamingResponse:
    """Stream a CSV of the most recent N events (chronological).
    Rate-limited: 1 export per hour per admin user."""
    _check_export_rate_limit(user.email or "")

    q = _build_audit_query(user_id, action, from_date, to_date)

    events = await AuditEvent.find(q).sort("-seq").limit(limit).to_list()
    events.reverse()  # chronological for the export

    def _gen():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "seq", "created_at", "user_id", "user_email", "action",
            "target_type", "target_id", "ip", "user_agent",
            "metadata", "prev_hash", "this_hash",
        ])
        for e in events:
            writer.writerow([
                e.seq,
                e.created_at.isoformat() if e.created_at else "",
                e.user_id or "",
                e.user_email or "",
                e.action,
                e.target_type or "",
                e.target_id or "",
                e.ip or "",
                (e.user_agent or "")[:200],
                (e.metadata or {}),
                e.prev_hash,
                e.this_hash,
            ])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    filename = f"audit-log-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        _gen(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/events.json", summary="Export audit log as JSON (admin, rate-limited)")
async def export_json(
    request: Request,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(10_000, ge=1, le=100_000),
    user: User = Depends(require_admin),
) -> StreamingResponse:
    """Stream a JSON array of the most recent N events.
    Rate-limited: 1 export per hour per admin user."""
    _check_export_rate_limit(user.email or "")

    q = _build_audit_query(user_id, action, from_date, to_date)

    events = await AuditEvent.find(q).sort("-seq").limit(limit).to_list()
    events.reverse()

    def _gen():
        yield "["
        for i, e in enumerate(events):
            if i > 0:
                yield ","
            yield json.dumps({
                "seq": e.seq,
                "user_id": e.user_id,
                "user_email": e.user_email,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "ip": e.ip,
                "user_agent": e.user_agent,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "metadata": e.metadata,
                "prev_hash": e.prev_hash,
                "this_hash": e.this_hash,
            }, default=str)
        yield "]"

    filename = f"audit-log-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    return StreamingResponse(
        _gen(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/verify-chain", summary="Verify the integrity of the audit hash chain (admin)")
async def verify_chain(
    limit: int = Query(10_000, ge=1, le=100_000),
    _: User = Depends(require_admin),
) -> dict:
    """Re-computes the hash chain and reports the first divergence (if any).

    For SOC2 / forensic use. May take a few seconds for large limits.
    """
    result = await audit.verify_chain(limit=limit)
    return result


@router.get("/actions", summary="List distinct action codes seen in the audit log (admin)")
async def list_actions(_: User = Depends(require_admin)) -> dict:
    """Useful for building a filter UI."""
    actions = await AuditEvent.find().distinct("action")
    return {"actions": sorted(actions)}
