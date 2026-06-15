"""SkillOpt Configuration — hyperparameters and settings for template optimization.

TASK-067 — Configuration for the forward/backward SkillOpt pipeline.
Based on arXiv:2605.23904v2 — SkillOpt: Self-Improving Code Generation Skills.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SkillOptConfig:
    """Configuration for a SkillOpt optimization run.

    Attributes:
        skill_path: Path to the codegen template file to optimize.
        skill_name: Human-readable name for logging/reporting.
        train_ideas: List of 40 idea dicts for training (forward pass).
        heldout_ideas: List of 10 idea dicts for validation gate.
        epochs: Number of optimization epochs (default 4).
        minibatch_size: Number of trajectories per minibatch for reflection.
        edit_budget: Max edits per optimization step (clipped).
        schedule: Decay schedule: "cosine" or "linear".
        epsilon: Acceptance threshold for validation gate improvement.
        output_dir: Where to store optimization artifacts.
        rejection_buffer_size: Max size of rejection buffer.
    """

    skill_path: str
    skill_name: str = ""
    train_ideas: list[dict] = field(default_factory=list)
    heldout_ideas: list[dict] = field(default_factory=list)
    epochs: int = 4
    minibatch_size: int = 8
    edit_budget: int = 4
    schedule: str = "cosine"
    epsilon: float = 0.01
    output_dir: str = ""
    rejection_buffer_size: int = 50

    # ── Tracked metrics ──
    initial_score: float = 0.0
    current_score: float = 0.0
    best_score: float = 0.0
    accepted_edits: int = 0
    rejected_edits: int = 0
    total_api_calls: int = 0

    def __post_init__(self):
        if not self.skill_name:
            self.skill_name = Path(self.skill_path).stem
        if not self.output_dir:
            self.output_dir = str(
                Path(__file__).resolve().parent
                / "skillopt_runs"
                / self.skill_name
            )

    def edit_budget_for_epoch(self, epoch: int) -> int:
        """Return edit budget for a given epoch using cosine or linear decay."""
        if self.schedule == "cosine":
            import math

            progress = epoch / max(self.epochs - 1, 1)
            budget = self.edit_budget * 0.5 * (1 + math.cos(math.pi * progress))
            return max(1, round(budget))
        else:  # linear
            decay = (self.epochs - 1 - epoch) / max(self.epochs - 1, 1)
            budget = max(1, self.edit_budget * 0.5 + self.edit_budget * 0.5 * decay)
            return round(budget)

    def to_dict(self) -> dict:
        return {
            "skill_path": self.skill_path,
            "skill_name": self.skill_name,
            "epochs": self.epochs,
            "minibatch_size": self.minibatch_size,
            "edit_budget": self.edit_budget,
            "schedule": self.schedule,
            "epsilon": self.epsilon,
            "train_ideas_count": len(self.train_ideas),
            "heldout_ideas_count": len(self.heldout_ideas),
        }

    def save(self, path: Optional[str] = None) -> str:
        """Save config as JSON for reproducibility."""
        p = path or str(Path(self.output_dir) / "skillopt_config.json")
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        )
        return p

    @classmethod
    def load(cls, path: str) -> "SkillOptConfig":
        """Load saved config."""
        data = json.loads(Path(path).read_text())
        return cls(**data)


# ── Default Score Weights ────────────────────────────

DEFAULT_SCORE_WEIGHTS = {
    "compiles": 0.30,
    "imports_valid": 0.15,
    "tests_pass": 0.20,
    "endpoints_match": 0.15,
    "models_match": 0.10,
    "no_orphan_code": 0.05,
    "lint_clean": 0.05,
}

# ── Bounded Edit Types ───────────────────────────────

EDIT_TYPES = ("add", "delete", "replace")

# ── Codegen Template Sections ────────────────────────

SKILL_SECTION_NAMES = {
    "datamodel": "Data model generation — entities → SQLModel models + schemas + CRUD",
    "api": "API codegen — endpoints → FastAPI routes + tests + rate limiting",
    "frontend": "Frontend codegen — features → React pages + 10K components",
    "project": "Project scaffold — Docker, CI/CD, configs, README, Makefile",
}

# ── Known Failure Patterns (seeded rules for optimizer) ──

SEEDED_FAILURE_PATTERNS: dict[str, list[str]] = {
    "datamodel": [
        "Missing Optional[] wrapper on nullable fields",
        "No Field(default=None, primary_key=True) on id columns",
        "Relationship back_populates mismatch with target model",
        "Using dict instead of JSON-serializable default values",
        "Forgot to import datetime for timestamp fields",
    ],
    "api": [
        "No response_model on decorated routes",
        "Missing Depends(get_session) in function signature",
        "status_code=204 routes returning response body",
        "No 404 check before returning object",
        "Hardcoded string instead of HTTPException detail",
    ],
    "frontend": [
        "Missing key prop in list rendering",
        "No loading/error states in data-fetching components",
        "Hardcoded API URLs instead of client instance",
        "Missing type annotations on functional components",
        "Inline styles instead of Tailwind utility classes",
    ],
    "project": [
        "Missing healthcheck on Docker services",
        "No .env.example file with required variables",
        "SECRET_KEY hardcoded as 'changeme'",
        "No CORS middleware in main.py",
        "Missing volumes for persistent data in docker-compose",
    ],
}
