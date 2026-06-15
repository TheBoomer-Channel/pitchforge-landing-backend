"""Shared project persistence helpers — MongoDB/Beanie edition."""

import logging
import uuid
from pathlib import Path
from typing import Optional

from ..database import Project, ResearchResult, Job
from ..research.models import ResearchReport

logger = logging.getLogger(__name__)


async def load_research_from_project(project_id: str) -> Optional[ResearchReport]:
    """Load existing ResearchReport from a project's stored research results."""
    research = await ResearchResult.find_one(ResearchResult.project_id == project_id)
    if research and research.report_json:
        report = ResearchReport(**research.report_json)
        logger.info(f"Loaded existing research from project {project_id}")
        return report
    return None


async def ensure_project_and_research(
    idea: str,
    report: ResearchReport,
    project_id: Optional[str] = None,
    user_id: str = "",
) -> str:
    """Ensure a project exists with persisted research."""
    if project_id:
        return project_id

    from ..worker import report_to_markdown

    project_id = str(uuid.uuid4())
    project = Project(
        id=project_id,
        user_id=user_id,
        title=idea[:255],
        idea_description=idea,
        status="complete",
    )
    await project.insert()

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

    logger.info(f"Auto-created project {project_id} with persisted research")
    return project_id


async def create_job_record(
    project_id: str,
    job_type: str,
    output_dir: str,
    extra: Optional[dict] = None,
) -> None:
    """Create a job record in MongoDB for state tracking."""
    try:
        out_path = Path(output_dir)
        files = [f.name for f in out_path.iterdir() if f.is_file()][:20] if out_path.exists() else []

        result = {"output_dir": str(output_dir), "files": files}
        if extra:
            result.update(extra)

        job = Job(
            id=str(uuid.uuid4()),
            project_id=project_id,
            type=job_type,
            status="complete",
            progress=100.0,
            result=result,
        )
        await job.insert()

        logger.info(f"Job record created: {job_type} → project {project_id}")
    except Exception as e:
        logger.warning(f"Failed to create {job_type} job record: {e}")
