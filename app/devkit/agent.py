"""Dev Agent — autonomous MVP development orchestrator.

Orchestrates the development cycle: task → implement → test → learn → commit → repeat.
The agent provides structure and reporting; implementation happens via the Hermes agent tools.
When connected to GitHub, each completed task auto-commits and pushes.
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .vault import ProjectVault
from .tasks import TaskManager, Task
from .testcycle import TestCycle

logger = logging.getLogger(__name__)


class DevAgent:
    """Autonomous development agent orchestrator."""

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.vault = ProjectVault(project_dir)
        self.tasks = TaskManager(project_dir)
        self.testcycle = TestCycle(project_dir)
        self.cycle_count = 0

    async def _auto_commit(self, message: str, task_id: Optional[str] = None) -> None:
        """Auto-commit and push to GitHub if a remote is configured."""
        try:
            from ..services.github_service import commit_and_push, get_status
            status = await get_status(str(self.project_dir))
            if status.get("initialized") and status.get("remote"):
                branch = status.get("branch") or "main"
                result = await commit_and_push(
                    str(self.project_dir),
                    message=message,
                    task_id=task_id,
                    branch=branch,
                )
                logger.info(f"Auto-commit [{result.get('status')}]: {message}")
                if result.get("sha"):
                    self.vault.log("git_commit", f"{task_id or 'auto'}: {result['sha']} — {message}")
        except ImportError:
            logger.debug("GitHub service not available, skipping auto-commit")
        except Exception as e:
            logger.warning(f"Auto-commit failed (non-blocking): {e}")

    def setup(self, planning_json: Optional[str] = None) -> dict:
        """Initialize project structure: vault + tasks from planning."""
        logger.info(f"Setting up dev environment for {self.project_dir}")

        # 1. Init vault
        vault_files = self.vault.init()
        self.vault.log("setup", f"Vault initialized with {len(vault_files)} files")

        # 2. Init tasks dir
        self.tasks.init()

        # 3. Generate tasks from planning if provided
        tasks_created = []
        if planning_json:
            tasks_created = self.tasks.generate_mvp_tasks(planning_json)
            self.vault.log("setup", f"Generated {len(tasks_created)} tasks from planning")
        else:
            # Create default setup tasks
            defaults = [
                Task(task_id="TASK-001", title="Initialize project structure", priority="P0",
                      description="Set up Docker, README, and basic project structure",
                      criteria=["Docker compose works", "README exists"]),
                Task(task_id="TASK-002", title="Configure database", priority="P0",
                      description="Set up database models and migrations",
                      criteria=["Models created", "Migration runs"]),
                Task(task_id="TASK-003", title="Implement auth", priority="P0",
                      description="Set up authentication flow",
                      criteria=["Login works", "Token validation works"]),
            ]
            for t in defaults:
                self.tasks.create_task(t)
                tasks_created.append(t)

        # 4. Check Docker availability
        docker_ok = self.testcycle.is_available()
        self.vault.log("setup", f"Docker available: {docker_ok}")

        return {
            "project_dir": str(self.project_dir),
            "vault_files": vault_files,
            "tasks_created": len(tasks_created),
            "docker_available": docker_ok,
            "status": "ready",
        }

    def status(self) -> dict:
        """Return full status of the development project."""
        task_stats = self.tasks.get_stats()
        docker_ok = self.testcycle.is_available()
        vault_files = self.vault.get_vault_structure()

        next_task = self.tasks.get_next_task()
        next_info = None
        if next_task:
            next_info = {
                "id": next_task.task_id,
                "title": next_task.title,
                "priority": next_task.priority,
                "criteria_count": len(next_task.criteria),
            }

        return {
            "project": str(self.project_dir),
            "timestamp": datetime.utcnow().isoformat(),
            "cycle": self.cycle_count,
            "tasks": task_stats,
            "next_task": next_info,
            "docker_available": docker_ok,
            "vault": vault_files,
        }

    def start_task(self, task_id: str) -> Optional[Task]:
        """Mark a task as in_progress and log it."""
        task = self.tasks.get_task(task_id)
        if not task:
            return None
        self.tasks.update_status(task_id, "in_progress")
        self.vault.log("task_start", f"{task_id}: {task.title}")
        return task

    async def complete_task(self, task_id: str, notes: str = "") -> Optional[Task]:
        """Mark a task as completed, log learnings, and auto-commit to GitHub."""
        task = self.tasks.get_task(task_id)
        if not task:
            return None
        self.tasks.update_status(task_id, "completed")
        self.vault.log("task_done", f"{task_id}: {task.title}")
        if notes:
            self.vault.learning(f"{task_id} learnings", notes)
        # Auto-commit on task completion
        await self._auto_commit(
            message=f"Complete {task.title}",
            task_id=task_id,
        )
        return task

    def fail_task(self, task_id: str, reason: str) -> Optional[Task]:
        """Mark a task as failed with reason."""
        task = self.tasks.get_task(task_id)
        if not task:
            return None
        self.tasks.update_status(task_id, "failed")
        self.vault.log("task_failed", f"{task_id}: {task.title} — {reason}")
        return task

    async def block_task(self, task_id: str, reason: str) -> Optional[Task]:
        """Mark a task as blocked."""
        task = self.tasks.get_task(task_id)
        if not task:
            return None
        self.tasks.update_status(task_id, "blocked")
        self.vault.log("task_blocked", f"{task_id}: {task.title} — {reason}")
        return task

    def run_cycle(self, test_endpoints: Optional[list[str]] = None) -> dict:
        """Run a single development cycle: start next task → implement → test.

        NOTE: This handles TESTING. Implementation must be done via Hermes tools.
        """
        self.cycle_count += 1

        # Get next task
        task = self.tasks.get_next_task()
        if not task:
            return {
                "cycle": self.cycle_count,
                "status": "all_done",
                "message": "No pending tasks. MVP complete!",
                "stats": self.tasks.get_stats(),
            }

        # Start task
        self.start_task(task.task_id)

        # Run test cycle
        test_results = self.testcycle.full_cycle(
            run_tests=True,
            check_endpoints=test_endpoints,
        )

        return {
            "cycle": self.cycle_count,
            "status": "need_implementation",
            "task": {
                "id": task.task_id,
                "title": task.title,
                "description": task.description,
                "criteria": task.criteria,
                "priority": task.priority,
            },
            "test_results": test_results,
            "stats": self.tasks.get_stats(),
        }

    def plan_from_specs(self, specs_dir: str) -> list[Task]:
        """Generate development plan from PitchForge planning specs.

        Reads the .json from planning and creates a task list.
        """
        planning_files = list(Path(specs_dir).glob("planning_report.json"))
        if not planning_files:
            # Look for any JSON in the specs dir
            planning_files = list(Path(specs_dir).glob("*.json"))

        if not planning_files:
            logger.warning(f"No planning JSON found in {specs_dir}")
            return []

        return self.tasks.generate_mvp_tasks(str(planning_files[0]))

    def generate_dev_plan_md(self, output_path: str) -> str:
        """Generate a DEVPLAN.md from current tasks."""
        tasks = self.tasks.list_tasks()
        stats = self.tasks.get_stats()

        lines = [
            f"# Development Plan",
            f"",
            f"**Status**: {stats['completed']}/{stats['total']} tasks completed",
            f"**In Progress**: {stats['in_progress']}",
            f"**Pending**: {stats['pending']}",
            f"**Blocked**: {stats['blocked']}",
            f"",
            f"## Tasks",
            f"",
        ]

        for t in tasks:
            status_icon = {
                "completed": "✅",
                "in_progress": "🔄",
                "pending": "⏳",
                "blocked": "🚫",
                "failed": "❌",
            }.get(t.status, "⏳")

            deps = f" (depends on: {', '.join(t.dependencies)})" if t.dependencies else ""
            lines.append(f"### {status_icon} {t.task_id}: {t.title} [{t.priority}]{deps}")
            if t.description:
                lines.append(f"{t.description}")
            if t.criteria:
                for c in t.criteria:
                    checked = "x" if t.status == "completed" else " "
                    lines.append(f"- [{checked}] {c}")
            lines.append("")

        content = "\n".join(lines)
        Path(output_path).write_text(content)
        self.vault.log("devplan", f"Generated {output_path}")
        return content

    def get_next_task_details(self) -> Optional[dict]:
        """Get detailed info about the next task to implement."""
        task = self.tasks.get_next_task()
        if not task:
            return None
        return {
            "id": task.task_id,
            "title": task.title,
            "description": task.description,
            "criteria": task.criteria,
            "priority": task.priority,
            "dependencies": task.dependencies,
            "estimate": task.estimate,
            "file_path": task.file_path,
        }
