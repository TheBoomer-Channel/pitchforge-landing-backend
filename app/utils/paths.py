"""Shared path utilities — output directories and idea slug generation.

Paths resolve via:
  1. PITCHFORGE_HOME env var (for Docker/CI)
  2. PROJECT_ROOT (parent of code/backend) as fallback
"""

import os
from pathlib import Path
import uuid

# Resolve base directory: env var → project root (code/backend/../..) → ~/code/startup-factory
_project_root = Path(__file__).resolve().parent.parent.parent.parent  # code/backend/app/utils → project root
# Backward compatible: PITCHFORGE_HOME takes precedence, then STARTUP_FACTORY_HOME
_home_env = os.environ.get("PITCHFORGE_HOME") or os.environ.get("STARTUP_FACTORY_HOME") or str(_project_root)
_home = Path(os.path.expanduser(_home_env))

# Base output directories (centralized)
GENERATED_DIR = _home / "generated"
PLANNING_DIR = _home / "planning_outputs"


def idea_slug(idea: str, max_len: int = 30) -> str:
    """Convert an idea string to a filesystem-safe slug."""
    return idea.lower().replace(" ", "-")[:max_len]


def make_output_dir(idea: str, base_dir: Path, sub_dir_len: int = 8) -> Path:
    """Create a timestamped output directory for an idea.
    
    Returns: Path like <base_dir>/<idea-slug>/<uuid-short>/
    """
    slug = idea_slug(idea)
    short_id = str(uuid.uuid4())[:sub_dir_len]
    out = base_dir / slug / short_id
    out.mkdir(parents=True, exist_ok=True)
    return out
