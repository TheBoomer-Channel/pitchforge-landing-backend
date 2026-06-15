"""Project version history — snapshot and restore project state.

Each time a project is updated (research, planning, codegen), a version
snapshot is saved so users can browse history and roll back.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import get_current_user
from ..database import User, Project, ProjectVersion
from ..services.projects import load_research_from_project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/versions", tags=["versions"])


@router.get("/{project_id}")
async def list_versions(
    project_id: str,
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
):
    """List all versions for a project, most recent first."""
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user.clerk_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    versions = await ProjectVersion.find(
        ProjectVersion.project_id == project_id,
    ).sort(-ProjectVersion.version).limit(limit).to_list()

    return {
        "project_id": project_id,
        "total": len(versions),
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "label": v.label,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "size_bytes": v.size_bytes,
                "files_count": len(v.files),
            }
            for v in versions
        ],
    }


@router.get("/{project_id}/{version_id}")
async def get_version(
    project_id: str,
    version_id: str,
    user: User = Depends(get_current_user),
):
    """Get the full snapshot data for a specific version."""
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user.clerk_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    version = await ProjectVersion.find_one(
        ProjectVersion.id == version_id,
        ProjectVersion.project_id == project_id,
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return {
        "id": version.id,
        "project_id": version.project_id,
        "version": version.version,
        "label": version.label,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "snapshot": version.snapshot,
        "files": version.files,
        "size_bytes": version.size_bytes,
    }


@router.post("/{project_id}/snapshot")
async def create_snapshot(
    project_id: str,
    label: str = Query("", description="Label for this snapshot"),
    user: User = Depends(get_current_user),
):
    """Create a new version snapshot of the project's current state."""
    project = await Project.find_one(Project.id == project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Authorization check
    if project.user_id != user.clerk_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this project")

    # Load research data
    research = await load_research_from_project(project_id)
    research_data = research.model_dump(mode="json") if research else None

    # Build snapshot
    snapshot = {
        "project": {
            "id": project.id,
            "title": project.title,
            "idea_description": project.idea_description,
            "target_market": project.target_market,
            "business_model": project.business_model,
            "status": project.status,
        },
        "research": research_data,
    }

    # Determine next version number
    last = await ProjectVersion.find(
        ProjectVersion.project_id == project_id,
    ).sort(-ProjectVersion.version).limit(1).to_list()
    next_version = (last[0].version + 1) if last else 1

    # Serialize for storage
    json_str = json.dumps(snapshot, default=str)
    version = ProjectVersion(
        project_id=project_id,
        version=next_version,
        label=label or f"v{next_version}",
        snapshot=snapshot,
        size_bytes=len(json_str),
    )
    await version.insert()

    logger.info(f"Version {next_version} created for project {project_id}: {label}")

    return {
        "id": version.id,
        "project_id": project_id,
        "version": next_version,
        "label": version.label,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "size_bytes": version.size_bytes,
    }
