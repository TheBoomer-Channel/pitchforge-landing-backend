"""Research API routes — MongoDB/Beanie edition with Clerk auth and daily limits."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, JSONResponse

from ..auth import get_current_user
from ..database import User, Project, ResearchResult
from ..email_lifecycle.templates import send_first_project_email
from ..services.research_runner import run_inline_research
from ..services.projects import create_job_record
from ..services.tier_limits import TierLimits
from ..worker import report_to_markdown
from ..webhooks.dispatcher import dispatch_webhooks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research", tags=["research"])


@router.post("/start")
async def start_research(
    idea: str = Query(..., description="Startup idea to research"),
    target_market: Optional[str] = Query(None, description="Target market/industry"),
    business_model: Optional[str] = Query(None, description="Business model"),
    user: User = Depends(get_current_user),
    request: Request = None,
):
    """Start a new research project with daily limit check and WebSocket progress."""
    limit_check = await TierLimits.check_research_limit(user)
    if not limit_check["allowed"]:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=limit_check["reason"])

    project_id = str(uuid.uuid4())
    project = Project(
        id=project_id,
        user_id=user.clerk_user_id,
        title=idea[:255],
        idea_description=idea,
        target_market=target_market,
        business_model=business_model,
        status="researching",
        pipeline={
            "research": {"status": "running", "job_id": None, "completed_at": None},
            "planning": {"status": "pending", "job_id": None, "completed_at": None},
            "codegen":  {"status": "pending", "job_id": None, "completed_at": None},
            "assets":   {"status": "pending", "job_id": None, "completed_at": None},
        },
    )
    await project.insert()

    # TASK-043 — Dispatch webhook: project.created
    try:
        await dispatch_webhooks("project.created", {
            "event": "project.created",
            "project_id": project_id,
            "title": project.title,
            "user_id": user.clerk_user_id,
            "timestamp": project.created_at.isoformat() if project.created_at else None,
        })
    except Exception as e:
        logger.warning(f"Webhook dispatch failed (non-fatal): {e}")

    # TASK-040 — Send "first project" email if this is the user's first project
    try:
        project_count = await Project.find(Project.user_id == user.clerk_user_id).count()
        if project_count == 1 and user.email and not getattr(user, 'email_opt_out', False):
            await send_first_project_email(
                user_id=user.clerk_user_id,
                to_email=user.email,
                name=user.name or "",
                project_title=project.title,
            )
            logger.info(f"First-project email sent: user={user.clerk_user_id}")
    except Exception as e:
        logger.warning(f"First-project email failed (non-fatal): {e}")

    # Get WS manager from app state
    ws_manager = None
    if request and hasattr(request.app.state, 'ws_manager'):
        ws_manager = request.app.state.ws_manager

    try:
        report = await run_inline_research(
            idea=idea,
            target_market=target_market or "",
            business_model=business_model or "",
            project_id=project_id,
            ws_manager=ws_manager,
        )
        markdown = report_to_markdown(report)
        research = ResearchResult(
            id=str(uuid.uuid4()),
            project_id=project_id,
            report_json=report.model_dump(mode="json"),
            report_markdown=markdown,
            summary=report.summary[:500] if report.summary else None,
            sources_used=report.sources_used,
            duration_ms=report.research_duration_ms,
        )
        await research.insert()
        project.status = "complete"

        # TASK-061 — Get job ID from create_job_record, then update pipeline
        job = await create_job_record(project_id, "research", "")
        project.pipeline["research"] = {
            "status": "complete",
            "job_id": job.id if job else None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        await project.save()
        await TierLimits.increment_research_count(user)

        # TASK-043 — Dispatch webhook: research.completed
        try:
            await dispatch_webhooks("research.completed", {
                "event": "research.completed",
                "project_id": project_id,
                "title": project.title,
                "user_id": user.clerk_user_id,
                "summary": report.summary[:500] if report.summary else None,
                "competitors_found": len(report.competitors),
                "duration_ms": report.research_duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning(f"Webhook dispatch failed (non-fatal): {e}")

        competitors_list = [{"name": c.name, "description": c.description, "website": c.website, "funding": c.funding, "business_model": c.business_model, "target_market": c.target_market, "pricing": c.pricing, "strengths": c.strengths, "weaknesses": c.weaknesses, "pain_points": c.pain_points, "source": c.source, "confidence": c.confidence} for c in report.competitors]
        gaps_list = [{"gap": g.gap, "severity": g.severity, "evidence": g.evidence, "source": g.source} for g in report.opportunity_gaps]

        return {
            "project_id": project_id, "status": "complete", "duration_ms": report.research_duration_ms,
            "summary": report.summary, "competitors_found": len(report.competitors),
            "competitors": competitors_list, "market_validation": report.market_validation.model_dump(mode="json") if report.market_validation else None,
            "opportunity_gaps": gaps_list, "recommended_mvp_features": report.recommended_mvp_features,
            "recommended_pricing": report.recommended_pricing_range, "recommended_positioning": report.recommended_positioning,
            "risk_factors": report.risk_factors, "sources_used": report.sources_used,
        }
    except Exception as e:
        project.status = "error"
        await project.save()

        # TASK-043 — Dispatch webhook: research.failed
        try:
            await dispatch_webhooks("research.failed", {
                "event": "research.failed",
                "project_id": project_id,
                "title": project.title,
                "user_id": user.clerk_user_id,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as wh_err:
            logger.warning(f"Webhook dispatch failed (non-fatal): {wh_err}")

        logger.error(f"Research failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}")
async def get_research(project_id: str):
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = {"project_id": project.id, "title": project.title, "status": project.status, "created_at": project.created_at.isoformat() if project.created_at else None}

    if project.status == "complete":
        research = await ResearchResult.find_one(ResearchResult.project_id == project_id)
        if research:
            result.update({"report_json": research.report_json, "report_markdown": research.report_markdown, "summary": research.summary, "duration_ms": research.duration_ms, "sources_used": research.sources_used})

    return result


@router.get("/{project_id}/download")
async def download_report(project_id: str, format: str = Query("json", description="Download format: json or markdown")):
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    research = await ResearchResult.find_one(ResearchResult.project_id == project_id)
    if not research:
        raise HTTPException(status_code=404, detail="Research not found for this project")

    if format == "markdown":
        return PlainTextResponse(content=research.report_markdown or "# No report available", media_type="text/markdown", headers={"Content-Disposition": f"attachment; filename=research-{project_id[:8]}.md"})
    else:
        return JSONResponse(content=research.report_json or {}, headers={"Content-Disposition": f"attachment; filename=research-{project_id[:8]}.json"})


@router.get("/cache/stats")
async def cache_stats():
    """Get semantic cache performance statistics.
    
    TASK-057 — Returns hit rate, false positive rate, and error counts
    for the semantic research cache.
    """
    from ..services.semantic_cache import get_cache
    cache = get_cache()
    return cache.get_stats()


@router.get("/")
async def list_research(limit: int = Query(10, ge=1, le=50), type: Optional[str] = Query(None, description="Filter by section")):
    projects = await Project.find().sort(-Project.created_at).limit(limit).to_list()

    if type and type != "research":
        job_type_map = {"planning": "planning", "codegen": "codegen", "assets": "generate"}
        job_type = job_type_map.get(type, type)
        from ..database import Job
        jobs = await Job.find(Job.type == job_type).to_list()
        valid_ids = {j.project_id for j in jobs}
        projects = [p for p in projects if p.id in valid_ids]

    return {"projects": [{"id": p.id, "title": p.title[:100], "status": p.status, "created_at": p.created_at.isoformat() if p.created_at else None} for p in projects], "total": len(projects)}
