"""Arq worker — runs research jobs asynchronously.

Usage:
    python -m app.worker
"""

import asyncio
import json
import logging
import os
from typing import Optional

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import Worker as ArqWorker

import sentry_sdk

from .config import settings
from .database import Project, ResearchResult, User, init_db
from .telemetry import init_telemetry
from .research.engine import ResearchEngine
from .research.http_client import ResearchHTTPClient
from .research.models import ResearchProgress, ResearchReport

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ── Sentry + OTel init (same config as main.py) ────────

try:
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            release=settings.SENTRY_RELEASE,
            traces_sample_rate=0.1,
            send_default_pii=False,
            max_request_body_size="medium",
        )
        logger.info(f"Worker Sentry initialized — environment={settings.SENTRY_ENVIRONMENT}")
    else:
        logger.info("Worker SENTRY_DSN not set — Sentry disabled")
    init_telemetry()
except Exception as e:
    logger.warning(f"Worker Sentry/OTel init failed (non-fatal): {e}")


# ── Redis Pool ─────────────────────────────────────────

async def get_redis():
    return await create_pool(RedisSettings.from_dsn(REDIS_URL))


# ── Progress Publisher ─────────────────────────────────

class RedisProgressPublisher:
    """Publishes progress updates to Redis pub/sub so WebSocket can relay them."""

    def __init__(self, project_id: str, redis_pool=None):
        self.project_id = project_id
        self._pool = redis_pool
        self._channel = f"research:progress:{project_id}"

    async def __call__(self, progress: ResearchProgress):
        """Called by ResearchEngine on each progress update."""
        progress.project_id = self.project_id
        try:
            pool = self._pool or await get_redis()
            await pool.publish(
                self._channel,
                progress.model_dump_json(),
            )
        except Exception as e:
            logger.warning(f"Progress publish error: {e}")

    async def publish_report(self, report: ResearchReport):
        """Publish final report."""
        try:
            pool = self._pool or await get_redis()
            await pool.publish(
                self._channel,
                json.dumps({
                    "type": "report",
                    "project_id": self.project_id,
                    "report": report.model_dump(mode="json"),
                }),
            )
        except Exception as e:
            logger.warning(f"Report publish error: {e}")


# ── Research Job ───────────────────────────────────────

async def run_research_job(ctx, project_id: str):
    """Arq job: execute research for a project.
    
    Called by Arq worker when a research job is dequeued.
    """
    logger.info(f"Starting research job for project {project_id}")

    pool = ctx.get("redis")
    publisher = RedisProgressPublisher(project_id, pool)

    try:
        # Update project status
        project = await Project.get(project_id)
        if project:
            project.status = "researching"
            await project.save()
        else:
            raise ValueError(f"Project {project_id} not found")

        # ── 1. Create ResearchEngine ───────────────────
        http_client = ResearchHTTPClient()
        engine = ResearchEngine(http_client=http_client)
        engine.on_progress(publisher)

        # ── 2. Run research ────────────────────────────
        report = await engine.run(
            idea=project.idea_description,
            target_market=project.target_market or "",
            business_model=project.business_model or "",
        )

        # ── 3. Save to database ────────────────────────
        research = ResearchResult(
            project_id=project_id,
            report_json=report.model_dump(mode="json"),
            report_markdown=report_to_markdown(report),
            summary=report.summary[:500] if report.summary else None,
            sources_used=report.sources_used,
            duration_ms=report.research_duration_ms,
        )
        await research.insert()

        if project:
            project.status = "complete"
            await project.save()

        # ── 4. Publish report ──────────────────────────
        await publisher.publish_report(report)

        logger.info(f"Research complete for {project_id} in {report.research_duration_ms}ms")

        return {
            "project_id": project_id,
            "status": "complete",
            "competitors": len(report.competitors),
            "duration_ms": report.research_duration_ms,
        }

    except Exception as e:
        logger.error(f"Research failed for {project_id}: {e}", exc_info=True)

        project = await Project.get(project_id)
        if project:
            project.status = "error"
            await project.save()

        await publisher(ResearchProgress(
            project_id=project_id,
            status="error",
            progress_pct=0.0,
            message=str(e),
        ))

        raise


# ── Markdown Generator ─────────────────────────────────

def report_to_markdown(report: ResearchReport) -> str:
    """Convert ResearchReport to readable markdown."""
    lines = []

    lines.append(f"# Research Report: {report.idea}")
    lines.append("")
    lines.append(f"**Generated:** {report.generated_at.isoformat()}")
    lines.append(f"**Duration:** {report.research_duration_ms}ms")
    lines.append(f"**Sources used:** {', '.join(report.sources_used)}")
    lines.append("")

    # Summary
    if report.summary:
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(report.summary)
        lines.append("")

    # Competitors
    if report.competitors:
        lines.append("## Competitors")
        lines.append("")
        for c in report.competitors:
            lines.append(f"### {c.name}")
            if c.description:
                lines.append(f"**Description:** {c.description}")
            if c.website:
                lines.append(f"**Website:** {c.website}")
            if c.funding:
                lines.append(f"**Funding:** {c.funding}")
            if c.business_model:
                lines.append(f"**Business Model:** {c.business_model}")
            if c.target_market:
                lines.append(f"**Target Market:** {c.target_market}")
            if c.pain_points:
                lines.append("**Pain Points:**")
                for p in c.pain_points:
                    lines.append(f"- {p}")
            if c.strengths:
                lines.append("**Strengths:**")
                for s in c.strengths:
                    lines.append(f"- {s}")
            if c.weaknesses:
                lines.append("**Weaknesses:**")
                for w in c.weaknesses:
                    lines.append(f"- {w}")
            lines.append(f"*Source: {c.source}*")
            lines.append("")

    # Market Validation
    mv = report.market_validation
    lines.append("## Market Validation")
    lines.append("")
    if mv.overall_sentiment:
        lines.append(f"**Overall Sentiment:** {mv.overall_sentiment}")
    if mv.reddit_posts_found:
        lines.append(f"**Reddit Posts Found:** {mv.reddit_posts_found}")
    if mv.reddit_sentiment:
        lines.append(f"**Reddit Sentiment:** {mv.reddit_sentiment}")
    if mv.hn_mentions:
        lines.append(f"**HN Mentions:** {mv.hn_mentions}")
    if mv.gh_similar_projects:
        lines.append(f"**GitHub Similar Projects:** {mv.gh_similar_projects}")
    if mv.common_complaints:
        lines.append("**Common Complaints:**")
        for c in mv.common_complaints:
            lines.append(f"- {c}")
    if mv.common_desires:
        lines.append("**Common Desires:**")
        for d in mv.common_desires:
            lines.append(f"- {d}")
    lines.append("")

    # Opportunity Gaps
    if report.opportunity_gaps:
        lines.append("## Opportunity Gaps")
        lines.append("")
        for g in report.opportunity_gaps:
            lines.append(f"### {g.gap}")
            lines.append(f"**Severity:** {g.severity}")
            if g.evidence:
                lines.append("**Evidence:**")
                for e in g.evidence:
                    lines.append(f"- {e}")
            lines.append(f"*Source: {g.source}*")
            lines.append("")

    # Recommendations
    if report.recommended_mvp_features:
        lines.append("## Recommended MVP Features")
        lines.append("")
        for f in report.recommended_mvp_features:
            lines.append(f"- {f}")
        lines.append("")

    if report.recommended_pricing_range:
        lines.append(f"**Recommended Pricing:** {report.recommended_pricing_range}")
        lines.append("")

    if report.recommended_positioning:
        lines.append(f"**Recommended Positioning:** {report.recommended_positioning}")
        lines.append("")

    if report.risk_factors:
        lines.append("## Risk Factors")
        lines.append("")
        for r in report.risk_factors:
            lines.append(f"- {r}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by PitchForge Research Engine*")

    return "\n".join(lines)


# ── Worker Setup ───────────────────────────────────────

async def _startup(ctx: dict) -> None:
    """Initialize DB connection on worker startup."""
    await init_db()


def create_worker() -> ArqWorker:
    """Create and return the Arq worker."""
    return ArqWorker(
        functions=[run_research_job],
        redis_settings=RedisSettings.from_dsn(REDIS_URL),
        on_startup=_startup,
        poll_delay=0.5,
        max_jobs=3,
        job_timeout=600,  # 10 min max per job
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker = create_worker()
    asyncio.run(worker.main())
