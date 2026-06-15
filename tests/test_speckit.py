"""Tests for speckit.py — SPEC.md, PLAN.md, TASK-*.md generation."""

import pytest
from pathlib import Path


def test_generate_speckit_artifacts_creates_all_files(mock_planning, tmp_output_dir):
    """Should create SPEC.md, PLAN.md, and task files."""
    from app.planning.codegen.speckit import generate_speckit_artifacts

    result = generate_speckit_artifacts(mock_planning, tmp_output_dir)

    assert Path(result["spec"]).exists()
    assert Path(result["plan"]).exists()
    assert result["task_count"] > 0
    assert len(result["tasks"]) == result["task_count"]


def test_spec_content_has_required_sections(mock_planning, tmp_output_dir):
    """SPEC.md should contain all required sections."""
    from app.planning.codegen.speckit import generate_speckit_artifacts

    result = generate_speckit_artifacts(mock_planning, tmp_output_dir)
    spec = Path(result["spec"]).read_text()

    assert "Product Overview" in spec
    assert "Functional Requirements" in spec
    assert "Non-Functional Requirements" in spec
    assert "Technical Architecture" in spec
    assert "Success Criteria" in spec
    assert "Risks & Mitigations" in spec


def test_plan_has_architecture_and_phases(mock_planning, tmp_output_dir):
    """PLAN.md should contain architecture and development phases."""
    from app.planning.codegen.speckit import generate_speckit_artifacts

    result = generate_speckit_artifacts(mock_planning, tmp_output_dir)
    plan = Path(result["plan"]).read_text()

    assert "Arquitectura General" in plan
    assert "Technology Stack" in plan
    assert "Development Phases" in plan
    assert "Validation Gates" in plan


def test_tasks_use_devagent_format(mock_planning, tmp_output_dir):
    """Each TASK file should use DevAgent format."""
    from app.planning.codegen.speckit import generate_speckit_artifacts

    result = generate_speckit_artifacts(mock_planning, tmp_output_dir)

    for task_path in result["tasks"]:
        content = Path(task_path).read_text()
        assert "**Status**:" in content
        assert "**Priority**:" in content
        assert "**Dependencies**:" in content
        assert "**Estimate**:" in content
        assert "## Acceptance Criteria" in content

        # Check at least one criteria checkbox
        assert "- [ ]" in content or "- [x]" in content


def test_foundation_tasks_first(mock_planning, tmp_output_dir):
    """First tasks should be foundation tasks."""
    from app.planning.codegen.speckit import generate_speckit_artifacts

    result = generate_speckit_artifacts(mock_planning, tmp_output_dir)

    first_task = Path(result["tasks"][0]).read_text()
    assert "project structure" in first_task.lower() or "docker" in first_task.lower() or "foundation" in first_task.lower()


def test_tasks_from_development_phases(mock_planning, tmp_output_dir):
    """Tasks should be derived from technical.development_phases."""
    from app.planning.codegen.speckit import generate_speckit_artifacts

    result = generate_speckit_artifacts(mock_planning, tmp_output_dir)

    # Should have more than just foundation tasks
    assert result["task_count"] >= 5
