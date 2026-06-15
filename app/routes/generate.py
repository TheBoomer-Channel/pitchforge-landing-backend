"""Generate API route — generates pitch deck, landing page, and pricing from an idea."""

import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..database import Job, Project as ProjectModel
from ..services.research_runner import run_inline_research
from ..services.projects import load_research_from_project, ensure_project_and_research, create_job_record
from ..utils.files import list_files as _list_files_dir
from ..utils.paths import GENERATED_DIR, make_output_dir
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/generate")
async def generate_assets(
    idea: str = Query(..., description="Startup idea to generate assets for"),
    project_id: Optional[str] = Query(None, description="Reuse existing project research"),
):
    """Generate pitch deck, landing page, and pricing page from an idea.
    
    If project_id is provided and has completed research, it reuses that data.
    Otherwise runs research inline and auto-creates a project.
    """
    report = None

    # 1. Load existing research from project
    if project_id:
        report = await load_research_from_project(project_id)

    # 2. Run research inline if no existing data
    if not report:
        try:
            report = await run_inline_research(idea=idea)
            project_id = await ensure_project_and_research(idea, report, project_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Research failed: {e}")

    # Generate assets
    try:
        from ..generator import generate_all

        out_dir = make_output_dir(report.idea, GENERATED_DIR)
        results = await generate_all(report, output_dir=str(out_dir))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    # Store job record for state tracking
    job = await create_job_record(project_id, "generate", str(out_dir))

    # TASK-061 — Update project pipeline
    proj = await ProjectModel.find_one(ProjectModel.id == project_id)
    if proj:
        proj.pipeline["assets"] = {
            "status": "complete",
            "job_id": job.id if hasattr(job, 'id') else None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        proj.assets_output_dir = str(out_dir)
        await proj.save()

    return {
        "idea": idea,
        "project_id": project_id,
        "status": "complete",
        "outputs": results,
        "output_dir": str(out_dir),
        "files": _list_files_dir(out_dir),
    }


# ── Helpers ────────────────────────────────────────────

async def _get_project_output_dir(project_id: str, job_type: str) -> Optional[Path]:
    """Look up a project's output directory from the Job table."""
    jobs = await Job.find(
        Job.project_id == project_id,
        Job.type == job_type,
        Job.status == "complete",
    ).sort(-Job.created_at).limit(1).to_list()
    if jobs and jobs[0].result and jobs[0].result.get("output_dir"):
        out_path = Path(jobs[0].result["output_dir"])
        if out_path.exists():
            return out_path
    return None


# ── Download & List endpoints ──────────────────────────

@router.get("/files/{project_id}")
async def list_generated_files(project_id: str):
    """List all generated asset files for a project, looked up from its output directory."""
    output_dir = await _get_project_output_dir(project_id, "generate")
    if not output_dir:
        return {"project_id": project_id, "output_dir": None, "files": [], "total": 0}

    files = _list_files_dir(output_dir)
    return {
        "project_id": project_id,
        "output_dir": str(output_dir),
        "files": files,
        "total": len(files),
    }


@router.get("/download/{project_id}/{filename:path}")
async def download_generated_file(project_id: str, filename: str):
    """Download a specific generated asset file by project ID."""
    output_dir = await _get_project_output_dir(project_id, "generate")
    if not output_dir:
        raise HTTPException(status_code=404, detail="No generated files found for this project")

    # Search recursively within the project's output directory
    for root, _, filenames in os.walk(str(output_dir)):
        if filename in filenames:
            candidate = Path(root) / filename
            media_type, _ = mimetypes.guess_type(str(candidate))
            return FileResponse(
                path=str(candidate),
                filename=filename,
                media_type=media_type or "application/octet-stream",
            )

    raise HTTPException(status_code=404, detail=f"File '{filename}' not found")
