"""Project management routes — MongoDB/Beanie edition."""

import os
import re
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from ..auth import get_current_user
from ..database import User, Project, ResearchResult, Job

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/{project_id}/state")
async def get_project_state(project_id: str):
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    state = {
        "project_id": project.id,
        "title": project.title,
        "status": project.status,
        "idea": project.idea_description,
        "target_market": project.target_market,
        "business_model": project.business_model,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "research": None, "planning": None, "generated": None, "jobs": [],
    }

    research = await ResearchResult.find_one(ResearchResult.project_id == project_id)
    if research:
        state["research"] = {"id": research.id, "summary": research.summary, "sources_used": research.sources_used, "duration_ms": research.duration_ms, "report_json": research.report_json, "report_markdown": research.report_markdown, "created_at": research.created_at.isoformat() if research.created_at else None}

    jobs = await Job.find(Job.project_id == project_id).sort(-Job.created_at).to_list()
    state["jobs"] = [{"id": j.id, "type": j.type, "status": j.status, "progress": j.progress, "result": j.result, "error": j.error, "created_at": j.created_at.isoformat() if j.created_at else None} for j in jobs]

    for j in jobs:
        if not j.result:
            continue
        if j.type == "planning" and j.status == "complete":
            state["planning"] = {"files": j.result.get("files", []), "output_dir": j.result.get("output_dir", "")}
        elif j.type == "generate" and j.status == "complete":
            state["generated"] = {"files": j.result.get("files", []), "output_dir": j.result.get("output_dir", "")}

    return state


@router.get("/{project_id}/pipeline")
async def get_project_pipeline(project_id: str):
    """TASK-061 — Return the full pipeline status for a project."""
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "project_id": project.id,
        "title": project.title,
        "status": project.status,
        "pipeline": project.pipeline,
        "outputs": {
            "research_result_id": project.research_result_id,
            "planning_output_dir": project.planning_output_dir,
            "codegen_output_dir": project.codegen_output_dir,
            "assets_output_dir": project.assets_output_dir,
        },
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


@router.get("/{project_id}/tasks")
async def get_project_tasks(project_id: str):
    project = await Project.find_one(Project.id == project_id)
    project_name = project.title if project else ""
    jobs = await Job.find(Job.project_id == project_id, Job.type == "planning", Job.status == "complete").sort(-Job.created_at).limit(1).to_list()
    job = jobs[0] if jobs else None

    if not job or not job.result or not job.result.get("output_dir"):
        return {"project_id": project_id, "tasks": _sample_tasks(), "project": project_name}

    from pathlib import Path
    tasks_dir = Path(job.result["output_dir"]) / "tasks"
    tasks = []

    if tasks_dir.exists():
        for f in sorted(tasks_dir.glob("*.md")):
            content = f.read_text()
            task_id_match = re.search(r"# (TASK-\d+): (.+)", content)
            task_id = task_id_match.group(1) if task_id_match else f.stem
            title = task_id_match.group(2).strip() if task_id_match else f.stem

            def _extract(field: str) -> str:
                m = re.search(rf"\*\*{field}\*\*:\s*(.+?)(?:\n|$)", content)
                return m.group(1).strip() if m else ""

            deps_raw = _extract("Dependencies")
            deps = [d.strip() for d in deps_raw.split(",") if d.strip()] if deps_raw else []
            desc_match = re.search(r"## Description\n(.+?)\n##", content, re.DOTALL)
            description = desc_match.group(1).strip() if desc_match else ""

            tasks.append({"id": task_id, "title": title, "status": _extract("Status") or "pending", "priority": _extract("Priority") or "P1", "dependencies": deps, "estimate": _extract("Estimate"), "description": description})

    if not tasks:
        tasks = _sample_tasks()

    return {"project_id": project_id, "tasks": tasks, "project": project_name, "output_dir": str(tasks_dir) if tasks_dir.exists() else ""}


@router.get("/{project_id}/outputs")
async def get_project_outputs(project_id: str):
    """TASK-063 — List all outputs separated by type: documents vs assets."""
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    documents = []
    assets = []

    # Collect from planning output dir
    if project.planning_output_dir:
        doc_dir = Path(project.planning_output_dir) / "documents"
        if doc_dir.exists():
            for f in sorted(doc_dir.glob("*.json")):
                size = f.stat().st_size
                documents.append({
                    "name": f.stem.replace("_", " ").title(),
                    "filename": f.name,
                    "path": str(f.relative_to(Path(project.planning_output_dir).parent)),
                    "size_bytes": size,
                    "size_human": _format_size(size),
                    "type": "json",
                    "category": "document",
                })
        # Also check root planning dir for md/html/json reports
        plan_dir = Path(project.planning_output_dir)
        if plan_dir.exists():
            for pattern in ["*.md", "*.html"]:
                for f in sorted(plan_dir.glob(pattern)):
                    if f.name.startswith("planning_"):
                        size = f.stat().st_size
                        documents.append({
                            "name": _doc_label(f.name),
                            "filename": f.name,
                            "path": str(f.relative_to(plan_dir.parent)),
                            "size_bytes": size,
                            "size_human": _format_size(size),
                            "type": f.suffix.lstrip("."),
                            "category": "document",
                        })

    # Collect from assets output dir
    if project.assets_output_dir:
        assets_dir = Path(project.assets_output_dir) / "assets"
        if not assets_dir.exists():
            assets_dir = Path(project.assets_output_dir)
        if assets_dir.exists():
            for f in sorted(assets_dir.glob("*.html")):
                size = f.stat().st_size
                assets.append({
                    "name": _asset_label(f.stem),
                    "filename": f.name,
                    "path": str(f.relative_to(assets_dir.parent)),
                    "size_bytes": size,
                    "size_human": _format_size(size),
                    "type": "html",
                    "category": "asset",
                    "preview_url": f"/api/projects/{project_id}/preview/{f.stem}",
                })

    return {
        "project_id": project_id,
        "documents": documents,
        "assets": assets,
        "total": len(documents) + len(assets),
    }


@router.get("/{project_id}/preview/{asset_type}")
async def preview_asset(project_id: str, asset_type: str):
    """TASK-063 — Serve asset HTML for preview (landing, pitch_deck, pricing)."""
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Search in assets output dir
    search_dirs = []
    if project.assets_output_dir:
        search_dirs.append(Path(project.assets_output_dir))
    if project.planning_output_dir:
        search_dirs.append(Path(project.planning_output_dir))

    filename = f"{asset_type}.html"
    for base_dir in search_dirs:
        if not base_dir.exists():
            continue
        # Check root level and assets/ subdir
        for candidate in [base_dir / filename, base_dir / "assets" / filename]:
            if candidate.exists():
                return HTMLResponse(content=candidate.read_text(), media_type="text/html")

    raise HTTPException(status_code=404, detail=f"Asset '{asset_type}' not found for project")


def _doc_label(filename: str) -> str:
    """Human-readable label for planning document filenames."""
    labels = {
        "planning_report.md": "Planning Report (Markdown)",
        "planning_report.json": "Planning Report (JSON)",
        "planning_dashboard.html": "Planning Dashboard",
    }
    return labels.get(filename, filename.replace("_", " ").replace(".md", "").replace(".html", "").title())


def _asset_label(stem: str) -> str:
    """Human-readable label for asset filenames."""
    labels = {
        "landing": "Landing Page",
        "pitch_deck": "Pitch Deck",
        "pricing": "Pricing Page",
    }
    return labels.get(stem, stem.replace("_", " ").title())


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ["B", "KB", "MB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"


def _sample_tasks() -> list[dict]:
    return [
        {"id": "TASK-001", "title": "Initialize project structure", "status": "completed", "priority": "P0", "dependencies": [], "estimate": "", "description": ""},
        {"id": "TASK-002", "title": "Configure database", "status": "completed", "priority": "P0", "dependencies": ["TASK-001"], "estimate": "", "description": ""},
        {"id": "TASK-003", "title": "Implement authentication", "status": "in_progress", "priority": "P0", "dependencies": ["TASK-002"], "estimate": "1h", "description": ""},
        {"id": "TASK-004", "title": "Build core API routes", "status": "pending", "priority": "P1", "dependencies": ["TASK-003"], "estimate": "2h", "description": ""},
        {"id": "TASK-005", "title": "Create frontend pages", "status": "pending", "priority": "P1", "dependencies": ["TASK-003"], "estimate": "3h", "description": ""},
        {"id": "TASK-006", "title": "Add validation & tests", "status": "pending", "priority": "P2", "dependencies": ["TASK-004"], "estimate": "1h", "description": ""},
    ]
