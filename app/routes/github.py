"""GitHub integration API routes — connect repo, commit, status."""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from ..database import Job
from ..services import github_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/github", tags=["github"])


# ── Pydantic models ────────────────────────────────────

class ConnectRequest(BaseModel):
    repo_url: str
    token: str
    branch: str = "main"


class CommitRequest(BaseModel):
    message: str
    task_id: Optional[str] = None
    branch: str = "main"


# ── Helpers ────────────────────────────────────────────

async def _get_project_output_dir(project_id: str) -> Optional[Path]:
    """Look up a project's output directory from the Job table (planning or generate)."""
    for job_type in ("planning", "generate"):
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


# ── Routes ─────────────────────────────────────────────


@router.post("/connect/{project_id}")
async def connect_github_repo(
    project_id: str,
    body: ConnectRequest = Body(...),
):
    """Connect a CodeGen project to a GitHub repository.

    Initializes git in the project's output directory, sets the remote origin
    with token-based authentication, and creates an initial commit.
    """
    output_dir = await _get_project_output_dir(project_id)
    if not output_dir:
        raise HTTPException(
            status_code=404,
            detail=f"No generated output directory found for project {project_id}. Generate code first.",
        )

    try:
        init_result = await github_service.init_repo(str(output_dir))
        connect_result = await github_service.connect_remote(
            str(output_dir), body.repo_url, body.token, body.branch
        )

        commit_result = await github_service.commit_and_push(
            str(output_dir),
            message=f"Initial commit — PitchForge project {project_id[:12]}",
            branch=body.branch,
            token=body.token,
        )

        return {
            "project_id": project_id,
            "output_dir": str(output_dir),
            "init": init_result,
            "remote": connect_result,
            "commit": commit_result,
        }
    except github_service.GitHubServiceError as e:
        # Sanitize token from error before returning
        safe = str(e).replace(body.token, "***TOKEN***") if body.token else str(e)
        raise HTTPException(status_code=400, detail=safe)
    except Exception as e:
        logger.error(f"GitHub connect failed", exc_info=True)
        raise HTTPException(status_code=500, detail="GitHub connect failed. Check repo URL and token.")


@router.post("/commit/{project_id}")
async def commit_project(
    project_id: str,
    body: CommitRequest = Body(...),
):
    """Stage all changes, commit, and push to the connected GitHub repo."""
    output_dir = await _get_project_output_dir(project_id)
    if not output_dir:
        raise HTTPException(status_code=404, detail="No output directory found")

    try:
        git_dir = output_dir / ".git"
        if not git_dir.exists():
            raise HTTPException(
                status_code=400,
                detail="Not a git repository. Connect to GitHub first via POST /api/github/connect/{project_id}",
            )

        result = await github_service.commit_and_push(
            str(output_dir), body.message, task_id=body.task_id, branch=body.branch
        )
        return {"project_id": project_id, "commit": result}
    except github_service.GitHubServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"GitHub commit failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Commit failed")


@router.get("/status/{project_id}")
async def repo_status(project_id: str):
    """Check the GitHub repo status for a project."""
    output_dir = await _get_project_output_dir(project_id)
    if not output_dir:
        return {"project_id": project_id, "connected": False, "status": None}

    try:
        status = await github_service.get_status(str(output_dir))
        return {
            "project_id": project_id,
            "connected": status.get("initialized", False) and bool(status.get("remote")),
            "status": status,
        }
    except Exception as e:
        logger.warning(f"GitHub status check failed: {e}")
        return {"project_id": project_id, "connected": False, "status": None, "error": str(e)}
