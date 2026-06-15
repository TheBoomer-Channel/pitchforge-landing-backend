"""GitHub integration service — git init, commit, push for DevKit projects.

Uses the system `git` CLI via subprocess. Requires git to be installed
in the runtime environment (added to Dockerfile).
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GitHubServiceError(Exception):
    """Raised when a git operation fails."""


_GITIGNORE_CONTENT = """# PitchForge — generated project
.env
.env.*
__pycache__/
*.pyc
node_modules/
.vault/
*.egg-info/
dist/
build/
.DS_Store
"""


def _sanitize(text: str, token: str) -> str:
    """Replace any occurrence of token with ***TOKEN***."""
    if not token:
        return text
    return text.replace(token, "***TOKEN***")


def _build_authenticated_url(repo_url: str, token: str) -> str:
    """Parse a GitHub URL and build an authenticated HTTPS URL with the token."""
    url = repo_url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    # Handle different URL formats
    if "github.com/" in url:
        parts = url.split("github.com/")[-1]
    elif ":" in url:
        # git@github.com:owner/repo.git format
        parts = url.split(":")[-1]
        if parts.endswith(".git"):
            parts = parts[:-4]
    else:
        raise GitHubServiceError(f"Unrecognized GitHub URL: {url}")

    owner_repo = parts.strip("/")
    return f"https://x-access-token:{token}@github.com/{owner_repo}.git"


async def _run_git(cmd: list[str], cwd: str | Path, env: Optional[dict] = None,
                   token: str = "") -> str:
    """Run a git command asynchronously and return stdout.

    If `token` is provided, it is sanitized from any error messages.
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=full_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode().strip()
    err = stderr.decode().strip()

    if proc.returncode != 0:
        safe_err = _sanitize(err, token)
        raise GitHubServiceError(f"git failed: {safe_err[:500]}")
    return out


# ── Public API ─────────────────────────────────────────


async def init_repo(project_dir: str) -> str:
    """Initialize a git repository in the project directory if not already one."""
    git_dir = Path(project_dir) / ".git"
    if git_dir.exists():
        return "already a git repository"

    await _run_git(["git", "init"], cwd=project_dir)
    await _run_git(["git", "config", "user.name", "PitchForge DevKit"], cwd=project_dir)
    await _run_git(["git", "config", "user.email", "devkit@startup-factory.ai"], cwd=project_dir)

    # Write .gitignore
    gitignore_path = Path(project_dir) / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(_GITIGNORE_CONTENT)

    return "git repository initialized"


async def connect_remote(project_dir: str, repo_url: str, token: str, branch: str = "main") -> str:
    """Set the remote origin for a git repo.

    Uses token-based HTTPS authentication.
    """
    authenticated_url = _build_authenticated_url(repo_url, token)

    # Remove existing origin if present
    try:
        await _run_git(["git", "remote", "remove", "origin"], cwd=project_dir)
    except GitHubServiceError:
        pass

    await _run_git(["git", "remote", "add", "origin", authenticated_url],
                   cwd=project_dir, token=token)
    await _run_git(["git", "checkout", "-b", branch], cwd=project_dir)

    # Extract owner/repo for display (without token)
    display_url = repo_url.rstrip("/")
    if display_url.endswith(".git"):
        display_url = display_url[:-4]
    if "github.com/" in display_url:
        display_url = display_url.split("github.com/")[-1]
    elif ":" in display_url:
        display_url = display_url.split(":")[-1]
        if display_url.endswith(".git"):
            display_url = display_url[:-4]
    display_url = display_url.strip("/")

    return f"Remote origin set to {display_url} on branch '{branch}'"


async def commit_and_push(
    project_dir: str,
    message: str,
    task_id: Optional[str] = None,
    branch: str = "main",
    token: str = "",
) -> dict:
    """Stage all changes, commit with a structured message, and push to remote."""
    await _run_git(["git", "add", "-A"], cwd=project_dir)

    status = await _run_git(["git", "status", "--porcelain"], cwd=project_dir)
    if not status.strip():
        return {"status": "nothing_to_commit", "sha": "", "message": ""}

    prefix = f"[{task_id}] " if task_id else ""
    full_message = f"{prefix}{message}"

    await _run_git(["git", "commit", "-m", full_message], cwd=project_dir)
    sha = await _run_git(["git", "rev-parse", "HEAD"], cwd=project_dir)

    try:
        await _run_git(
            ["git", "push", "-u", "origin", branch, "--no-verify"],
            cwd=project_dir,
            env={"GIT_TERMINAL_PROMPT": "0"},
            token=token,
        )
        pushed = True
    except GitHubServiceError:
        logger.warning("Push failed (remote may not be set)")
        pushed = False

    return {
        "status": "committed" if pushed else "committed_local",
        "sha": sha[:12],
        "message": full_message,
        "pushed": pushed,
    }


async def get_status(project_dir: str) -> dict:
    """Get the git status of a project directory."""
    git_dir = Path(project_dir) / ".git"
    if not git_dir.exists():
        return {"initialized": False, "branch": None, "remote": None, "ahead": None, "uncommitted": 0}

    try:
        branch = await _run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_dir)
    except GitHubServiceError:
        branch = None

    try:
        remote = await _run_git(["git", "remote", "get-url", "origin"], cwd=project_dir)
        # Mask token: keep only after the last @
        remote = remote.split("@")[-1] if "@" in remote else remote
    except GitHubServiceError:
        remote = None

    try:
        ahead = await _run_git(["git", "rev-list", "--count", "@{upstream}", "HEAD"], cwd=project_dir)
    except GitHubServiceError:
        ahead = None

    try:
        uncommitted = await _run_git(["git", "status", "--porcelain"], cwd=project_dir)
        uncommitted_count = len([l for l in uncommitted.split("\n") if l.strip()])
    except GitHubServiceError:
        uncommitted_count = 0

    try:
        last_log = await _run_git(["git", "log", "-1", "--format=%h %s"], cwd=project_dir)
    except GitHubServiceError:
        last_log = None

    return {
        "initialized": True,
        "branch": branch,
        "remote": remote,
        "ahead": ahead,
        "uncommitted": uncommitted_count,
        "last_commit": last_log,
    }
