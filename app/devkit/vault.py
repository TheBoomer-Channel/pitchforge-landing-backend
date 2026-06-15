"""Project Vault — Obsidian-style memory per project.

Creates a .vault/ directory in the project with structured markdown files
for architecture decisions, specs, progress log, and learnings.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VAULT_FILES = {
    "README.md": "# .vault — Project Memory\n\nThis vault stores architecture decisions, specs, progress, and learnings.\n",
    "architecture.md": """# Architecture Decisions

## Stack

_Record technology choices and rationale here._

""",
    "decisions.md": """# Architecture Decision Records

## ADR Format
- **Date**: YYYY-MM-DD
- **Context**: Why this decision was needed
- **Decision**: What was decided
- **Consequences**: What trade-offs this creates

""",
    "specs.md": """# Specifications

## Features

_Record feature specs, API endpoints, data models here._

""",
    "progress.md": """# Development Progress

## Log

| Date | Task | Status | Notes |
|------|------|--------|-------|

""",
    "learnings.md": """# Learnings & Gotchas

_Record bugs, workarounds, things to remember._

""",
}


class ProjectVault:
    """Manages project memory as an Obsidian-style markdown vault."""

    def __init__(self, project_dir: str):
        self.root = Path(project_dir)
        self.vault_dir = self.root / ".vault"

    def init(self) -> list[str]:
        """Create vault directory with initial files."""
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        created = []
        for filename, content in VAULT_FILES.items():
            path = self.vault_dir / filename
            if not path.exists():
                path.write_text(content)
                created.append(filename)
        return created

    def log(self, event: str, detail: str = "") -> None:
        """Append an entry to progress.md with timestamp."""
        progress = self.vault_dir / "progress.md"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not progress.exists():
            progress.write_text("# Development Progress\n\n| Date | Event | Detail |\n|------|-------|--------|\n")
        with open(progress, "a") as f:
            f.write(f"| {timestamp} | {event} | {detail} |\n")

    def adr(self, title: str, context: str, decision: str, consequences: str) -> None:
        """Append an Architecture Decision Record."""
        decisions = self.vault_dir / "decisions.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"""
## {title}

- **Date**: {timestamp}
- **Context**: {context}
- **Decision**: {decision}
- **Consequences**: {consequences}

"""
        with open(decisions, "a") as f:
            f.write(entry)

    def learning(self, title: str, body: str) -> None:
        """Record a learning/gotcha."""
        learnings = self.vault_dir / "learnings.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"""
### {title} ({timestamp})

{body}

"""
        with open(learnings, "a") as f:
            f.write(entry)

    def get_progress(self) -> str:
        """Return the full progress log."""
        progress = self.vault_dir / "progress.md"
        if progress.exists():
            return progress.read_text()
        return "No progress yet."

    def get_vault_structure(self) -> dict:
        """Return file listing and sizes."""
        files = {}
        for f in self.vault_dir.glob("*.md"):
            content = f.read_text()
            files[f.name] = {
                "size": len(content),
                "lines": content.count("\n") + 1,
                "updated": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            }
        return files

    def search(self, query: str) -> list[dict]:
        """Search across all vault files."""
        results = []
        for f in self.vault_dir.glob("*.md"):
            content = f.read_text()
            if query.lower() in content.lower():
                # Find matching lines
                for i, line in enumerate(content.split("\n"), 1):
                    if query.lower() in line.lower():
                        results.append({
                            "file": f.name,
                            "line": i,
                            "text": line.strip()[:150],
                        })
        return results

    def read(self, filename: str) -> Optional[str]:
        """Read a specific vault file."""
        path = self.vault_dir / filename
        if path.exists():
            return path.read_text()
        return None

    def write(self, filename: str, content: str) -> None:
        """Write/overwrite a vault file."""
        (self.vault_dir / filename).write_text(content)

    def append(self, filename: str, content: str) -> None:
        """Append to a vault file."""
        with open(self.vault_dir / filename, "a") as f:
            f.write(content)
