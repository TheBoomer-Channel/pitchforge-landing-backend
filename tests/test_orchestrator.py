"""Tests for orchestrator.py — CodegenPipeline integration."""

import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_pipeline_runs_all_steps(mock_planning, tmp_output_dir):
    """CodegenPipeline.run() should execute all 5 steps."""
    from app.planning.codegen.orchestrator import CodegenPipeline

    pipeline = CodegenPipeline()
    result = await pipeline.run(mock_planning, tmp_output_dir)

    assert result["total_files"] > 10
    assert "stats" in result
    assert "validation" in result

    # Check that all 5 steps ran
    stats = result["stats"]
    assert "scaffold_files" in stats
    assert "model_files" in stats
    assert "api_files" in stats
    assert "frontend_files" in stats


@pytest.mark.asyncio
async def test_pipeline_creates_project_json(mock_planning, tmp_output_dir):
    """Should create project.json manifest."""
    from app.planning.codegen.orchestrator import CodegenPipeline

    pipeline = CodegenPipeline()
    await pipeline.run(mock_planning, tmp_output_dir)

    manifest = Path(tmp_output_dir) / "project.json"
    assert manifest.exists()

    import json
    data = json.loads(manifest.read_text())
    assert "idea" in data
    assert "codegen_version" in data
    assert data["codegen_version"] == "2.0"


@pytest.mark.asyncio
async def test_pipeline_validation_passes(mock_planning, tmp_output_dir):
    """Validation gate should pass for complete project."""
    from app.planning.codegen.orchestrator import CodegenPipeline

    pipeline = CodegenPipeline()
    result = await pipeline.run(mock_planning, tmp_output_dir)

    validation = result["validation"]
    assert validation["success"] is True
    assert len(validation["missing_dirs"]) == 0
    assert len(validation["missing_files"]) == 0


@pytest.mark.asyncio
async def test_pipeline_cleans_previous_output(mock_planning, tmp_output_dir):
    """Should clean previous output before generating."""
    from app.planning.codegen.orchestrator import CodegenPipeline

    # Create a dummy file in the output
    dummy = Path(tmp_output_dir) / "old_file.txt"
    dummy.write_text("old")

    pipeline = CodegenPipeline()
    await pipeline.run(mock_planning, tmp_output_dir)

    # Old file should be removed
    assert not dummy.exists()


@pytest.mark.asyncio
async def test_pipeline_run_and_zip(mock_planning, tmp_output_dir):
    """run_and_zip should create a zip file."""
    from app.planning.codegen.orchestrator import CodegenPipeline

    pipeline = CodegenPipeline()
    zip_path = await pipeline.run_and_zip(mock_planning, tmp_output_dir)

    assert zip_path.endswith(".zip")
    assert Path(zip_path).exists()


@pytest.mark.asyncio
async def test_validate_project_detects_missing_dirs(mock_planning, tmp_output_dir):
    """_validate_project should detect missing directories."""
    from app.planning.codegen.orchestrator import _validate_project

    # Don't create any dirs — should fail
    result = _validate_project(tmp_output_dir)
    assert result["success"] is False
    assert len(result["missing_dirs"]) > 0
    assert len(result["missing_files"]) > 0


@pytest.mark.asyncio
async def test_speckit_integration_in_pipeline(mock_planning, tmp_output_dir):
    """Pipeline should generate speckit artifacts when enabled."""
    from app.planning.codegen.orchestrator import CodegenPipeline
    import os

    pipeline = CodegenPipeline()
    result = await pipeline.run(mock_planning, tmp_output_dir, generate_speckit=True)

    # Check spec files exist somewhere in the output
    spec_exists = (Path(tmp_output_dir) / "SPEC.md").exists()
    plan_exists = (Path(tmp_output_dir) / "PLAN.md").exists()
    
    # Tasks might be in a tasks/ subdirectory
    tasks_dir = Path(tmp_output_dir) / "tasks"
    task_count = len(list(tasks_dir.glob("*.md"))) if tasks_dir.exists() else 0
    
    # At minimum, spec and plan should exist
    assert spec_exists or plan_exists, f"Neither SPEC.md nor PLAN.md found in {tmp_output_dir}"
    assert task_count > 0, f"No TASK-*.md files in {tasks_dir} (exists: {tasks_dir.exists()})"
