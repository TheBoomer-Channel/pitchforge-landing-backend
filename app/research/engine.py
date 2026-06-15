"""Research Engine — orchestrator that runs all sources and synthesizes results.

Design:
- Runs enabled sources in order of priority (parallel when possible)
- Each source returns BaseSourceResult
- Engine collects all results and passes to ReportSynthesizer
- Synthesizer uses LLM to generate final ResearchReport
- Fully async with graceful degradation (one source failing doesn't break others)
"""

import asyncio
import logging
import time
from typing import Optional, Protocol

from opentelemetry import trace

from .base_source import BaseSource, get_enabled_sources, list_sources
from .http_client import ResearchHTTPClient
from .models import (
    BaseSourceResult,
    Competitor,
    MarketSizing,
    MarketValidation,
    OpportunityGap,
    ResearchProgress,
    ResearchReport,
)
from .report import ReportSynthesizer

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


# ── Progress Callback ──────────────────────────────────

class ProgressCallback(Protocol):
    """Called by engine to report progress."""
    async def __call__(self, progress: ResearchProgress) -> None: ...


# ── Engine ─────────────────────────────────────────────

class ResearchEngine:
    """Orchestrates multi-source research for a startup idea.
    
    Usage:
        engine = ResearchEngine()
        report = await engine.run("AI-powered freight matching for Angola")
    
    To add a new source:
        1. Create a new class in sources/ extending BaseSource
        2. It auto-registers via __init_subclass__
        3. Done — engine will discover and run it
    """

    def __init__(self, http_client: Optional[ResearchHTTPClient] = None):
        self.http_client = http_client or ResearchHTTPClient()
        self.synthesizer = ReportSynthesizer()
        self._progress_callback: Optional[ProgressCallback] = None

    def on_progress(self, callback: ProgressCallback):
        """Set a callback for progress updates."""
        self._progress_callback = callback

    async def _emit_progress(self, progress: ResearchProgress):
        """Emit progress if callback is set."""
        if self._progress_callback:
            try:
                await self._progress_callback(progress)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    async def run(
        self,
        idea: str,
        target_market: str = "",
        business_model: str = "",
        source_names: Optional[list[str]] = None,
    ) -> ResearchReport:
        """Execute full research pipeline.
        
        Args:
            idea: The startup idea to research.
            target_market: Optional target market/industry.
            business_model: Optional business model description.
            source_names: Optional list of source names to use (default: all enabled).
            
        Returns:
            ResearchReport with all synthesized findings.
        """
        start_time = time.monotonic()
        context = {
            "target_market": target_market,
            "business_model": business_model,
        }

        query = idea
        if target_market:
            query += f" in {target_market}"

        # ── 1. Determine sources to run ─────────────────
        if source_names:
            from .base_source import get_source
            sources_to_run = []
            for name in source_names:
                cls = get_source(name)
                if cls and cls.enabled:
                    sources_to_run.append(cls)
                else:
                    logger.warning(f"Source '{name}' not found or disabled")
        else:
            enabled = get_enabled_sources()
            sources_to_run = []
            for name in enabled:
                from .base_source import get_source
                cls = get_source(name)
                if cls:
                    sources_to_run.append(cls)

        # Sort by priority
        sources_to_run.sort(key=lambda s: s.priority)

        total_sources = len(sources_to_run)
        sources_done = []

        # ── 2. Emit start ──────────────────────────────
        await self._emit_progress(ResearchProgress(
            project_id="",  # Set by caller
            status="started",
            progress_pct=5.0,
            message=f"Starting research with {total_sources} sources",
            sources_total=total_sources,
        ))

        # ── 3. Run sources in parallel (with concurrency limits) ──
        raw_results: dict[str, BaseSourceResult] = {}
        semaphores: dict[str, asyncio.Semaphore] = {}

        async def run_source(source_cls) -> tuple[str, BaseSourceResult]:
            name = source_cls.name
            sem = semaphores.get(name, asyncio.Semaphore(source_cls.max_concurrency))
            async with sem:
                # Create OTel span for this source
                with tracer.start_as_current_span(
                    f"research.source.{name}",
                    attributes={
                        "source.name": name,
                        "source.description": source_cls.description,
                        "source.priority": source_cls.priority,
                    },
                ) as span:
                    try:
                        await self._emit_progress(ResearchProgress(
                            project_id="",
                            status="searching",
                            progress_pct=10.0 + (len(sources_done) / total_sources) * 50,
                            message=f"Searching {source_cls.description}...",
                            current_source=name,
                            sources_done=list(sources_done),
                            sources_total=total_sources,
                        ))

                        instance = source_cls(http_client=self.http_client)
                        result = await instance.search(query, context=context)

                        # Close if has close method
                        if hasattr(instance, "close"):
                            try:
                                await instance.close()
                            except Exception:
                                pass

                        span.set_attribute("source.success", result.success)
                        span.set_attribute("source.result_count", len(result.data))

                        sources_done.append(name)
                        return name, result

                    except Exception as e:
                        span.set_attribute("source.success", False)
                        span.record_exception(e)
                        logger.error(f"Source '{name}' failed: {e}", exc_info=True)
                        sources_done.append(name)
                        return name, BaseSourceResult(
                            source=name,
                            success=False,
                            error=str(e)[:500],
                        )

        # Launch all sources concurrently
        tasks = [run_source(cls) for cls in sources_to_run]
        done_count = 0

        for coro in asyncio.as_completed(tasks):
            name, result = await coro
            raw_results[name] = result
            done_count += 1

            await self._emit_progress(ResearchProgress(
                project_id="",
                status="searching",
                progress_pct=10.0 + (done_count / total_sources) * 50,
                message=f"Source {name} completed ({done_count}/{total_sources})",
                current_source=name,
                sources_done=sources_done,
                sources_total=total_sources,
            ))

        # ── 4. Synthesize report ────────────────────────
        await self._emit_progress(ResearchProgress(
            project_id="",
            status="synthesizing",
            progress_pct=70.0,
            message="Synthesizing findings into research report...",
            sources_done=sources_done,
            sources_total=total_sources,
        ))

        report = await self.synthesizer.synthesize(
            idea=idea,
            query=query,
            target_market=target_market,
            raw_results=raw_results,
        )

        # ── 5. Add metadata ─────────────────────────────
        duration_ms = int((time.monotonic() - start_time) * 1000)
        report.idea = idea
        report.research_duration_ms = duration_ms
        report.sources_used = sources_done
        report.source_quality = {
            name: 1.0 if result.success else 0.0
            for name, result in raw_results.items()
        }
        report.raw_sources = raw_results

        await self._emit_progress(ResearchProgress(
            project_id="",
            status="done",
            progress_pct=100.0,
            message=f"Research complete. Found {len(report.competitors)} competitors, "
                    f"{len(report.opportunity_gaps)} opportunity gaps.",
            sources_done=sources_done,
            sources_total=total_sources,
        ))

        return report
