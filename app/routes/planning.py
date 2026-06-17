"""Planning API routes — REST endpoints for the planning pipeline."""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
import mimetypes

from ..database import Job, Project as ProjectModel
from ..planning import PlanningPipeline
from ..planning.document_catalog import CATEGORIES, resolve_documents
from ..planning.codegen.feature_extractor import extract_features, map_features_to_phases
from ..services.research_runner import run_inline_research
from ..services.projects import load_research_from_project, ensure_project_and_research, create_job_record
from ..utils.files import format_size, guess_file_type, list_files as _list_files_dir
from ..utils.paths import PLANNING_DIR, make_output_dir
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/plan", tags=["planning"])


@router.post("/start")
async def start_planning(
    idea: str = Query(..., description="Startup idea to plan"),
    project_id: Optional[str] = Query(None, description="Reuse existing project research"),
    research_json_path: Optional[str] = Query(None, description="Path to existing research JSON"),
    documents: Optional[str] = Query(None, description="Comma-separated document IDs or 'mvp'/'all'"),
    use_llm: bool = Query(True, description="Use LLM for generation (set false for fast deterministic mode)"),
):
    """Run the full planning pipeline: PRD → Functional → Financial → Technical.
    
    If project_id is provided and has completed research, it reuses that data.
    Otherwise runs research inline and auto-creates a project.
    """
    pipeline = PlanningPipeline()

    # 1. Load existing research from project
    report = None
    if project_id:
        report = await load_research_from_project(project_id)

    # 2. Load from file path if provided
    if not report and research_json_path and Path(research_json_path).exists():
        data = json.loads(Path(research_json_path).read_text())
        from ..research.models import ResearchReport
        report = ResearchReport(**data)
        logger.info(f"Loaded research from {research_json_path}")

    # 3. Run research inline if no existing data
    if not report:
        os.environ["RESEARCH_USE_LLM"] = str(use_llm).lower()
        report = await run_inline_research(idea=idea)
        project_id = await ensure_project_and_research(idea, report, project_id)

    # Run pipeline with document selection
    out_dir = make_output_dir(report.idea, PLANNING_DIR)
    doc_list = documents.split(",") if documents else None
    results = await pipeline.run_and_save(report, output_dir=str(out_dir), documents=doc_list, use_llm=use_llm)

    # Also generate pitch/landing/pricing (skip if use_llm=false — requires AI image gen)
    if use_llm:
        try:
            from ..generator import generate_all
            gen_results = await generate_all(report, output_dir=str(out_dir))
            results.update(gen_results)
        except Exception as e:
            logger.warning(f"Generator failed: {e}")
    else:
        logger.info("Skipping generate_all (use_llm=false)")

    # Store job record for state tracking
    job = await create_job_record(project_id, "planning", str(out_dir), {
        "duration_ms": results["duration_ms"],
    })

    # TASK-061 — Update project pipeline
    proj = await ProjectModel.find_one(ProjectModel.id == project_id)
    if proj:
        proj.pipeline["planning"] = {
            "status": "complete",
            "job_id": job.id if hasattr(job, 'id') else None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        proj.planning_output_dir = str(out_dir)
        await proj.save()

    # Collect file info for the frontend (top-level only — non-recursive)
    files = []
    if out_dir.exists():
        for f in sorted(out_dir.iterdir()):
            if f.is_file():
                size = f.stat().st_size
                files.append({
                    "filename": f.name,
                    "size": size,
                    "size_human": format_size(size),
                    "type": guess_file_type(f.name),
                })

    # TASK-068 — Attach feature anchors extracted from PRD
    try:
        feature_anchors = extract_features(output.prd) if output and output.prd else []
        feature_phases = map_features_to_phases(feature_anchors)
    except Exception:
        feature_anchors = []
        feature_phases = {}

    return {
        "idea": idea,
        "project_id": project_id,
        "status": "complete",
        "duration_ms": results["duration_ms"],
        "outputs": results,
        "output_dir": str(out_dir),
        "files": files,
        "feature_anchors": [f.model_dump(mode="json") for f in feature_anchors],
        "feature_phases": feature_phases,
    }


@router.get("/documents/catalog")
async def get_document_catalog():
    """TASK-065 — Return the full document catalog with categories and priorities."""
    return {
        "categories": CATEGORIES,
        "presets": {
            "mvp": {"label": "MVP Minimum (10 docs)", "count": 10},
            "all": {"label": "All Documents (27 docs)", "count": 27},
        },
        "total_documents": sum(len(cat["documents"]) for cat in CATEGORIES),
    }


@router.get("/download/{project_id}/{filename:path}")
async def download_planning_file(
    project_id: str,
    filename: str,
):
    """Download a generated planning file (HTML, MD, JSON) by project ID.

    Looks up the project's output directory via the Job table for accurate
    project-to-file mapping.
    """
    output_dir = await _get_planning_output_dir(project_id)
    if not output_dir:
        raise HTTPException(status_code=404, detail="No planning outputs found for this project")

    # Search recursively within the project's output directory
    for root, _, filenames in os.walk(str(output_dir)):
        if filename in filenames:
            file_path = Path(root) / filename
            mime_type, _ = mimetypes.guess_type(filename)
            return FileResponse(
                path=str(file_path),
                media_type=mime_type or "application/octet-stream",
                filename=filename,
            )

    raise HTTPException(status_code=404, detail=f"File '{filename}' not found")


@router.get("/files/{project_id}")
async def list_project_files(
    project_id: str,
):
    """List all generated files for a project, looked up from its output directory."""
    output_dir = await _get_planning_output_dir(project_id)
    if not output_dir:
        return {"project_id": project_id, "output_dir": None, "files": [], "total": 0}

    files = _list_files_dir(output_dir)
    for f in files:
        f["download_url"] = f"/api/plan/download/{project_id}/{f['filename']}"

    return {"project_id": project_id, "output_dir": str(output_dir), "files": files, "total": len(files)}


@router.get("/output")
async def list_planning_outputs(
    limit: int = Query(10, ge=1, le=50),
):
    """List recent planning output directories."""
    if not PLANNING_DIR.exists():
        return {"outputs": [], "total": 0}

    dirs = sorted(PLANNING_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    outputs = []
    for d in dirs:
        files = [f.name for f in d.iterdir()] if d.is_dir() else []
        outputs.append({
            "name": d.name,
            "path": str(d),
            "files": files,
            "created": d.stat().st_mtime,
        })

    return {"outputs": outputs, "total": len(outputs)}


# ── Helpers ────────────────────────────────────────────

async def _get_planning_output_dir(project_id: str) -> Optional[Path]:
    """Look up a project's planning output directory from the Job table."""
    jobs = await Job.find(
        Job.project_id == project_id,
        Job.type == "planning",
        Job.status == "complete",
    ).sort(-Job.created_at).limit(1).to_list()
    if jobs and jobs[0].result and jobs[0].result.get("output_dir"):
        out_path = Path(jobs[0].result["output_dir"])
        if out_path.exists():
            return out_path
    return None
