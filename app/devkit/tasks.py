"""Task Manager — .md task files for autonomous development.

Each task is a markdown file in tasks/ with frontmatter-like structure.
Tasks can be: pending, in_progress, completed, blocked, failed.

Task file format:
```markdown
# TASK-001: Task Title

**Status**: pending
**Priority**: P0
**Dependencies**: TASK-000
**Estimate**: 30m

## Description
What needs to be done.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Notes
Implementation details, decisions.
```
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class Task:
    """Represents a single development task."""

    VALID_STATUSES = ("pending", "in_progress", "completed", "blocked", "failed")

    def __init__(
        self,
        task_id: str,
        title: str,
        status: str = "pending",
        priority: str = "P1",
        dependencies: Optional[List[str]] = None,
        estimate: str = "",
        description: str = "",
        criteria: Optional[List[str]] = None,
        notes: str = "",
        file_path: str = "",
    ):
        self.task_id = task_id
        self.title = title
        self.status = status if status in self.VALID_STATUSES else "pending"
        self.priority = priority
        self.dependencies = dependencies or []
        self.estimate = estimate
        self.description = description
        self.criteria = criteria or []
        self.notes = notes
        self.file_path = file_path

    @classmethod
    def from_file(cls, path: Path) -> "Task":
        """Parse a task from markdown file."""
        content = path.read_text()

        def extract(field: str) -> str:
            m = re.search(rf"\*\*{field}\*\*:\s*(.+?)(?:\n|$)", content)
            return m.group(1).strip() if m else ""

        task_id_match = re.search(r"# TASK-(\d+): (.+)", content)
        task_id = f"TASK-{task_id_match.group(1)}" if task_id_match else path.stem
        title = task_id_match.group(2).strip() if task_id_match else path.stem

        deps_raw = extract("Dependencies")
        deps = [d.strip() for d in deps_raw.split(",") if d.strip()] if deps_raw else []

        criteria = []
        for m in re.finditer(r"- \[([ x])\] (.+)", content):
            criteria.append(m.group(2).strip())

        # Description is text between ## Description and ## Acceptance Criteria
        desc_match = re.search(r"## Description\n(.+?)\n##", content, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else ""

        # Notes is text between ## Notes and EOF
        notes_match = re.search(r"## Notes\n(.+)", content, re.DOTALL)
        notes = notes_match.group(1).strip() if notes_match else ""

        return cls(
            task_id=task_id,
            title=title,
            status=extract("Status"),
            priority=extract("Priority"),
            dependencies=deps,
            estimate=extract("Estimate"),
            description=description,
            criteria=criteria,
            notes=notes,
            file_path=str(path),
        )

    def to_markdown(self) -> str:
        """Render task as markdown file."""
        dep_line = ", ".join(self.dependencies) if self.dependencies else ""
        criteria_lines = "\n".join(
            f"- [{'x' if self.status == 'completed' else ' '}] {c}"
            for c in self.criteria
        )
        return f"""# {self.task_id}: {self.title}

**Status**: {self.status}
**Priority**: {self.priority}
**Dependencies**: {dep_line}
**Estimate**: {self.estimate}

## Description

{self.description}

## Acceptance Criteria

{criteria_lines}

## Notes

{self.notes}
"""

    def save(self, tasks_dir: Path) -> Path:
        """Save task to markdown file."""
        self.file_path = str(tasks_dir / f"{self.task_id.lower().replace(' ', '-')}.md")
        path = Path(self.file_path)
        path.write_text(self.to_markdown())
        return path


class TaskManager:
    """Manages task lifecycle in a project."""

    def __init__(self, project_dir: str):
        self.tasks_dir = Path(project_dir) / "tasks"

    def init(self) -> None:
        """Create tasks directory."""
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self, status: Optional[str] = None) -> list[Task]:
        """List all tasks, optionally filtered by status."""
        tasks = []
        for f in sorted(self.tasks_dir.glob("*.md")):
            task = Task.from_file(f)
            if status is None or task.status == status:
                tasks.append(task)
        return tasks

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        for f in self.tasks_dir.glob("*.md"):
            task = Task.from_file(f)
            if task.task_id == task_id:
                return task
        return None

    def create_task(self, task: Task) -> Path:
        """Create a new task file."""
        path = task.save(self.tasks_dir)
        logger.info(f"Created task: {task.task_id} -> {path}")
        return path

    def update_status(self, task_id: str, new_status: str) -> bool:
        """Update task status."""
        if new_status not in Task.VALID_STATUSES:
            return False
        task = self.get_task(task_id)
        if not task:
            return False
        task.status = new_status
        task.save(self.tasks_dir)
        return True

    def get_next_task(self) -> Optional[Task]:
        """Get the highest-priority pending task whose dependencies are met."""
        pending = self.list_tasks("pending")
        blocked = self.list_tasks("blocked")
        completed_ids = {t.task_id for t in self.list_tasks("completed")}

        # Check pending tasks
        for task in sorted(pending, key=lambda t: t.priority):
            deps_met = all(d in completed_ids for d in task.dependencies)
            if deps_met:
                return task

        # Check blocked tasks whose dependencies are now met
        for task in blocked:
            deps_met = all(d in completed_ids for d in task.dependencies)
            if deps_met:
                self.update_status(task.task_id, "pending")
                return task

        return None

    def get_stats(self) -> dict:
        """Return task statistics."""
        all_tasks = self.list_tasks()
        return {
            "total": len(all_tasks),
            "pending": len([t for t in all_tasks if t.status == "pending"]),
            "in_progress": len([t for t in all_tasks if t.status == "in_progress"]),
            "completed": len([t for t in all_tasks if t.status == "completed"]),
            "blocked": len([t for t in all_tasks if t.status == "blocked"]),
            "failed": len([t for t in all_tasks if t.status == "failed"]),
        }

    def generate_mvp_tasks(self, planning_output_path: str) -> list[Task]:
        """Auto-generate task list from a planning report JSON."""
        import json

        path = Path(planning_output_path)
        if not path.exists():
            return []

        data = json.loads(path.read_text())
        tasks = []
        idx = 0

        # Phase 1: Foundation
        tech = data.get("technical", {})
        phases = tech.get("development_phases", [])
        if phases:
            for phase in phases:
                for task_name in phase.get("tasks", []):
                    idx += 1
                    tasks.append(Task(
                        task_id=f"TASK-{idx:03d}",
                        title=task_name,
                        status="pending",
                        priority="P0" if idx < 5 else "P1",
                        estimate=phase.get("duration", ""),
                        description=task_name,
                        criteria=["Implementation complete", "Tests passing", "Docker build OK"],
                    ))
        else:
            # Generate from features
            features = data.get("functional", {}).get("core_features", [])
            for f in features:
                idx += 1
                tasks.append(Task(
                    task_id=f"TASK-{idx:03d}",
                    title=f.get("name", f.get("description", f"Feature {idx}"))[:80],
                    status="pending",
                    priority=f.get("priority", "P1"),
                    estimate="",
                    description=f.get("description", ""),
                    criteria=f.get("acceptance_criteria", ["Works end-to-end"]),
                ))

        for task in tasks:
            self.create_task(task)

        return tasks
