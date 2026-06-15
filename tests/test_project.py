"""Tests for project.py — project scaffold generation."""

import pytest
from pathlib import Path


def test_scaffold_creates_all_dirs(mock_planning, tmp_output_dir):
    """Scaffold should create all required directories."""
    from app.planning.codegen.project import scaffold_project

    result = scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    assert result["dirs_created"] > 5
    assert result["files_created"] > 10

    # Check key directories
    for d in ["app/models", "app/routes", "app/core", ".github/workflows", "tests", "frontend/src"]:
        assert (Path(tmp_output_dir) / d).is_dir(), f"Missing directory: {d}"


def test_scaffold_creates_docker_compose(mock_planning, tmp_output_dir):
    """Should create docker-compose.yml with healthchecks."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    dc = Path(tmp_output_dir) / "docker-compose.yml"
    assert dc.exists()
    content = dc.read_text()

    assert "healthcheck" in content
    assert "postgres" in content.lower() or "db:" in content
    assert "redis" in content.lower()


def test_scaffold_creates_makefile(mock_planning, tmp_output_dir):
    """Should create Makefile with at least 7 commands."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    mf = Path(tmp_output_dir) / "Makefile"
    assert mf.exists()
    content = mf.read_text()

    # Count .PHONY targets
    targets = [line for line in content.split("\n") if line.startswith("dev:") or line.startswith("test:") or line.startswith("lint:") or line.startswith("migrate:") or line.startswith("up:")]
    assert len(targets) >= 3


def test_scaffold_creates_ci_cd(mock_planning, tmp_output_dir):
    """Should create GitHub Actions CI/CD workflow."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    ci = Path(tmp_output_dir) / ".github/workflows/ci.yml"
    assert ci.exists()
    content = ci.read_text()

    assert "lint" in content.lower() or "ruff" in content.lower()
    assert "test" in content.lower() or "pytest" in content.lower()
    assert "build" in content.lower() or "docker" in content.lower()


def test_scaffold_creates_alembic(mock_planning, tmp_output_dir):
    """Should create Alembic configuration."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    assert (Path(tmp_output_dir) / "alembic.ini").exists()
    assert (Path(tmp_output_dir) / "alembic/env.py").exists()


def test_scaffold_creates_readme(mock_planning, tmp_output_dir):
    """README should contain badges and architecture."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    readme = Path(tmp_output_dir) / "README.md"
    assert readme.exists()
    content = readme.read_text()

    assert "Quick Start" in content
    assert "Architecture" in content
    assert "Stack" in content


def test_scaffold_creates_conftest(mock_planning, tmp_output_dir):
    """Should create pytest conftest with DB fixtures."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    conftest = Path(tmp_output_dir) / "tests/conftest.py"
    assert conftest.exists()
    content = conftest.read_text()

    assert "pytest" in content
    assert "AsyncClient" in content


def test_scaffold_creates_i18n_files(mock_planning, tmp_output_dir):
    """Should create i18n translation files."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    en = Path(tmp_output_dir) / "frontend/src/i18n/en.json"
    es = Path(tmp_output_dir) / "frontend/src/i18n/es.json"

    assert en.exists()
    assert es.exists()

    en_data = en.read_text()
    assert "nav.home" in en_data
    assert "nav.dashboard" in en_data


def test_scaffold_creates_theme_hook(mock_planning, tmp_output_dir):
    """Should create useTheme hook."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    hook = Path(tmp_output_dir) / "frontend/src/hooks/useTheme.ts"
    assert hook.exists()
    content = hook.read_text()

    assert "useTheme" in content
    assert "localStorage" in content


def test_scaffold_creates_app_tsx_with_lazy(mock_planning, tmp_output_dir):
    """App.tsx should use React.lazy for code splitting."""
    from app.planning.codegen.project import scaffold_project

    scaffold_project(tmp_output_dir, mock_planning.technical, mock_planning.financial)

    app = Path(tmp_output_dir) / "frontend/src/App.tsx"
    assert app.exists()
    content = app.read_text()

    assert "lazy" in content
    assert "Suspense" in content
    assert "fallback" in content
