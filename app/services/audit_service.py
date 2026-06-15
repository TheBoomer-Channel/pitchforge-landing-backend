"""Audit service — TASK-014.

Single entry point for recording audit events. Wraps:
  1. Sequence-number assignment (atomic via a small lock-free counter doc).
  2. Hash chain computation.
  3. Persistence.

Usage:
  from app.services.audit_service import audit
  await audit.log(
      action=AuditAction.AUTH_LOGIN_SUCCESS,
      user_id=user.clerk_user_id,
      user_email=user.email,
      ip=request.client.host,
      user_agent=request.headers.get("user-agent"),
  )
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from beanie import Document
from pydantic import Field

from ..models.audit import (
    GENESIS_HASH,
    AuditAction,
    AuditEvent,
    compute_chain_hash,
)
from ..database import client

logger = logging.getLogger(__name__)


class _AuditCounter(Document):
    """Single-row counter for the global audit sequence number."""
    _id: str = "global"  # type: ignore[assignment]
    seq: int = 0

    class Settings:
        name = "audit_counter"


_counter_lock = asyncio.Lock()


async def _next_seq() -> int:
    """Atomically increment the global sequence counter."""
    async with _counter_lock:
        counter = await _AuditCounter.find_one(_AuditCounter._id == "global")
        if not counter:
            counter = _AuditCounter(seq=1)
        else:
            counter.seq += 1
        await counter.save()
        return counter.seq


async def _get_latest_hash() -> str:
    """Get the this_hash of the most recent event (or GENESIS)."""
    latest = await AuditEvent.find().sort("-seq").limit(1).first_or_none()
    if not latest:
        return GENESIS_HASH
    return latest.this_hash


class AuditService:
    """Public facade."""

    async def log(
        self,
        action: str,
        *,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[AuditEvent]:
        """Record a single audit event. Failures are logged but do not raise
        (we never want auditing to break user flows).
        """
        if not client:
            # No DB configured — skip silently
            return None
        try:
            seq = await _next_seq()
            prev_hash = await _get_latest_hash()
            metadata = metadata or {}
            # Hash payload must exclude prev_hash and this_hash
            row = {
                "seq": seq,
                "user_id": user_id,
                "user_email": user_email,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "ip": ip,
                "user_agent": user_agent,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata,
            }
            this_hash = compute_chain_hash(prev_hash, row)
            event = AuditEvent(
                seq=seq,
                user_id=user_id,
                user_email=user_email,
                action=action,
                target_type=target_type,
                target_id=target_id,
                ip=ip,
                user_agent=user_agent,
                metadata=metadata,
                prev_hash=prev_hash,
                this_hash=this_hash,
            )
            await event.insert()
            return event
        except Exception as e:
            logger.error(f"audit.log failed (action={action}): {e}")
            return None

    async def verify_chain(self, limit: int = 10_000) -> dict:
        """Re-compute the hash chain over the most recent `limit` events
        and report the first divergence (if any).

        Returns {"ok": bool, "checked": int, "first_bad_seq": int|None}
        """
        latest = await AuditEvent.find().sort("-seq").limit(1).first_or_none()
        if not latest:
            return {"ok": True, "checked": 0, "first_bad_seq": None}

        # Walk backwards from the latest event for `limit` rows
        events = await AuditEvent.find().sort("-seq").limit(limit).to_list()
        events.reverse()  # oldest first

        expected_prev = GENESIS_HASH
        checked = 0
        for ev in events:
            if ev.prev_hash != expected_prev:
                return {"ok": False, "checked": checked, "first_bad_seq": ev.seq}
            row = {
                "seq": ev.seq,
                "user_id": ev.user_id,
                "user_email": ev.user_email,
                "action": ev.action,
                "target_type": ev.target_type,
                "target_id": ev.target_id,
                "ip": ev.ip,
                "user_agent": ev.user_agent,
                "created_at": ev.created_at.isoformat(),
                "metadata": ev.metadata,
            }
            expected_this = compute_chain_hash(ev.prev_hash, row)
            if ev.this_hash != expected_this:
                return {"ok": False, "checked": checked, "first_bad_seq": ev.seq}
            expected_prev = ev.this_hash
            checked += 1
        return {"ok": True, "checked": checked, "first_bad_seq": None}


# Singleton
audit = AuditService()
