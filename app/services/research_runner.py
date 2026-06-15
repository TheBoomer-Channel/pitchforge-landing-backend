"""Shared research runner — centralizes the inline research engine pattern.

Used by research.py, planning.py, and generate.py routes.
Supports optional WebSocket progress broadcasting.

TASK-057 — Semantic caching: before running the engine, checks if a semantically
similar query is already cached. After running, stores the result in cache.
Hit rate target: >40% with <5% false positives at threshold 0.92.
"""

import logging
from typing import Optional, Callable, Awaitable

from ..research.models import ResearchProgress, ResearchReport
from ..research.http_client import ResearchHTTPClient

logger = logging.getLogger(__name__)


async def run_inline_research(
    idea: str,
    target_market: str = "",
    business_model: str = "",
    use_llm: bool = True,
    project_id: str = "",
    ws_manager=None,
) -> ResearchReport:
    """Run the research engine inline and return the report.
    
    If ws_manager is provided, progress updates are broadcast via WebSocket.
    This is the single entry point for running research, used by all routes.
    
    TASK-057 — Semantic caching: checks cache before engine.run(), stores after.
    """
    
    # ── 0. Semantic cache lookup (TASK-057) ────────────
    try:
        from .semantic_cache import get_cache
        cache = get_cache()
        cached = await cache.lookup(idea)
        if cached:
            report_dict = cached["response"]
            report = ResearchReport(**report_dict)
            logger.info(
                f"Semantic cache HIT: returned cached research for '{idea[:60]}' "
                f"(similarity={cached['similarity']})"
            )
            return report
    except Exception as e:
        logger.warning(f"Semantic cache lookup failed (non-fatal): {e}")
    
    from ..research import ResearchEngine
    
    http_client = ResearchHTTPClient()
    engine = ResearchEngine(http_client=http_client)
    
    # Connect WebSocket progress broadcasting
    if ws_manager:
        async def ws_progress(progress: ResearchProgress):
            progress.project_id = project_id or idea[:20]
            await ws_manager.broadcast(
                project_id or idea[:20],
                {
                    "type": "step_progress",
                    "step": progress.current_source or progress.status,
                    "pct": round(progress.progress_pct, 1),
                    "message": progress.message,
                    "status": progress.status,
                    "sources_done": progress.sources_done,
                    "sources_total": progress.sources_total,
                },
            )
        engine.on_progress(ws_progress)
    
    report = await engine.run(
        idea=idea,
        target_market=target_market,
        business_model=business_model,
    )
    
    # ── 5. Store in semantic cache (TASK-057) ──────────
    try:
        from .semantic_cache import get_cache
        cache = get_cache()
        await cache.store(idea, report.model_dump(mode="json"))
    except Exception as e:
        logger.warning(f"Semantic cache store failed (non-fatal): {e}")
    
    # Broadcast completion
    if ws_manager:
        await ws_manager.broadcast(
            project_id or idea[:20],
            {
                "type": "job_complete",
                "step": "research",
                "message": f"Research complete. Found {len(report.competitors)} competitors.",
                "pct": 100,
            },
        )
    
    logger.info(
        f"Research complete: {len(report.competitors)} competitors, "
        f"{len(report.opportunity_gaps)} gaps, "
        f"{report.research_duration_ms}ms"
    )
    
    return report
