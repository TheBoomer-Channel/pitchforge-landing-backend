"""Feature Extractor — extracts features with [Fn] anchors from PRDSpec for codegen tasks.

TASK-068 — Part of the Spec-Driven Development pipeline.
Provides mapping from PRD features to codegen tasks with traceability.
"""

from typing import Optional
from pydantic import BaseModel, Field

from ..models import PRDSpec, FeatureAnchor


class CodegenTask(BaseModel):
    """A code generation task tied to one or more PRD features."""
    id: str  # "T1.1", "T2.3", ...
    covers: list[str] = Field(default_factory=list)  # ["F1"], ["F2", "F3"]
    files: list[str] = Field(default_factory=list)  # Files to create/modify
    description: str = ""
    order: int = 0


class FeatureCoverage(BaseModel):
    """Coverage report: which PRD features are covered by codegen tasks."""
    total: int
    covered: int
    uncovered: list[str] = Field(default_factory=list)
    coverage_pct: float = 0.0


def extract_features(prd: PRDSpec) -> list[FeatureAnchor]:
    """Extract features with [Fn] anchors from a PRD spec.
    
    If PRD has features list, return those.
    Otherwise, derive from user_stories for backward compatibility.
    """
    if prd.features:
        return prd.features
    
    # Backward compatibility: create anchors from user_stories
    anchors = []
    for i, story in enumerate(prd.user_stories or []):
        name = story.replace("As a user, I want to ", "").split(" so that")[0].strip()
        anchors.append(FeatureAnchor(
            anchor=f"F{i+1}",
            name=name[:80] if name else f"Feature {i+1}",
            description=story,
            priority="P0" if i < 3 else ("P1" if i < 6 else "P2"),
            acceptance_criteria=["Works end-to-end"],
        ))
    return anchors


def verify_coverage(
    features: list[FeatureAnchor],
    tasks: list[CodegenTask],
) -> FeatureCoverage:
    """Verify that all PRD features are covered by codegen tasks.
    
    Returns a coverage report with uncovered feature anchors.
    
    Example:
        >>> features = [FeatureAnchor(anchor="F1", name="Login")]
        >>> tasks = [CodegenTask(id="T1.1", covers=["F1"])]
        >>> verify_coverage(features, tasks)
        FeatureCoverage(total=1, covered=1, uncovered=[], coverage_pct=100.0)
    """
    covered = set()
    for task in tasks:
        covered.update(task.covers)
    
    uncovered = [f.anchor for f in features if f.anchor not in covered]
    
    return FeatureCoverage(
        total=len(features),
        covered=len(covered),
        uncovered=uncovered,
        coverage_pct=round((len(covered) / max(len(features), 1)) * 100, 1),
    )


def map_features_to_phases(
    features: list[FeatureAnchor],
) -> dict[str, list[str]]:
    """Group feature anchors by priority phase for roadmap display.
    
    Returns:
        {"P0": ["F1", "F2"], "P1": ["F3", "F4"], "P2": ["F5"]}
    """
    phases: dict[str, list[str]] = {"P0": [], "P1": [], "P2": []}
    for f in features:
        priority = f.priority if f.priority in ("P0", "P1", "P2") else "P2"
        phases[priority].append(f.anchor)
    return phases
