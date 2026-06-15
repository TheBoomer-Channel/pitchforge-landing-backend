"""WebSocket manager — broadcasts job progress to connected clients.

Adapted from Startup Engine's api/app/ws.py
Merged into PitchForge — June 2026
"""

import logging
from typing import Any, Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections grouped by job_id.

    Usage:
        manager = ConnectionManager()
        await manager.connect(job_id, websocket)
        await manager.broadcast(job_id, {"type": "progress", "pct": 50})
        await manager.disconnect(job_id, websocket)
    """

    def __init__(self):
        self.active: Dict[str, List[WebSocket]] = {}

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.setdefault(job_id, []).append(websocket)
        logger.debug(f"WS connected: job={job_id} total={len(self.active[job_id])}")

    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        try:
            self.active[job_id].remove(websocket)
            if not self.active[job_id]:
                del self.active[job_id]
        except (ValueError, KeyError):
            pass
        logger.debug(f"WS disconnected: job={job_id}")

    async def broadcast(self, job_id: str, event: Dict[str, Any]) -> None:
        """Send a JSON event to all subscribers of a job_id."""
        if job_id not in self.active:
            return
        disconnected = []
        for ws in self.active[job_id]:
            try:
                await ws.send_json(event)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            await self.disconnect(job_id, ws)

    # ── Convenience emitters ───────────────────────────

    async def emit_progress(
        self, job_id: str, pct: float, message: str = "", step: str = ""
    ) -> None:
        await self.broadcast(
            job_id,
            {
                "type": "step_progress",
                "step": step,
                "pct": round(pct, 1),
                "message": message,
            },
        )

    async def emit_complete(
        self, job_id: str, step: str, output: Any = None
    ) -> None:
        await self.broadcast(
            job_id,
            {"type": "step_complete", "step": step, "output": output},
        )

    async def emit_job_complete(self, job_id: str, result: Any = None) -> None:
        await self.broadcast(
            job_id,
            {"type": "job_complete", "result": result},
        )

    async def emit_error(self, job_id: str, error: str) -> None:
        await self.broadcast(
            job_id,
            {"type": "job_error", "error": error},
        )


# Singleton — shared across routes and workers
manager = ConnectionManager()
