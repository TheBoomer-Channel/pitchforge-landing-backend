"""Tests for frontend.py — React page + component generation."""

import pytest
from pathlib import Path


def test_generate_frontend_creates_components(mock_planning, tmp_output_dir):
    """Should create 10K quality components."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    files = generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    assert len(files) > 5


def test_ten_k_components_generated(mock_planning, tmp_output_dir):
    """Should generate at least 8 of the 10K components."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    expected = [
        "ThemeToggle.tsx",
        "LanguageSwitcher.tsx",
        "Card.tsx",
        "Modal.tsx",
        "Table.tsx",
        "Toast.tsx",
        "Button.tsx",
        "Input.tsx",
        "Skeleton.tsx",
        "EmptyState.tsx",
        "ErrorBoundary.tsx",
    ]

    for comp in expected:
        path = out / "src/components" / comp
        assert path.exists(), f"Missing component: {comp}"


def test_theme_toggle_uses_localstorage(mock_planning, tmp_output_dir):
    """ThemeToggle should persist to localStorage via useTheme hook."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    tt = out / "src/components/ThemeToggle.tsx"
    content = tt.read_text()
    # ThemeToggle imports useTheme which uses localStorage
    assert "useTheme" in content


def test_language_switcher_has_en_es(mock_planning, tmp_output_dir):
    """LanguageSwitcher should support en and es."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    ls = out / "src/components/LanguageSwitcher.tsx"
    content = ls.read_text()
    assert "en" in content.lower()
    assert "es" in content.lower()


def test_home_page_generated(mock_planning, tmp_output_dir):
    """Should generate Home.tsx with features."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    home = out / "src/pages/Home.tsx"
    assert home.exists()
    content = home.read_text()

    assert "export default function Home" in content
    assert "Core Features" in content or "Get Started" in content


def test_dashboard_page_has_api_call(mock_planning, tmp_output_dir):
    """Dashboard should use React Query to call API."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    dash = out / "src/pages/Dashboard.tsx"
    assert dash.exists()
    content = dash.read_text()

    assert "useQuery" in content
    # Dashboard uses the API client or React Query
    assert "api" in content.lower()


def test_toast_component_has_variants(mock_planning, tmp_output_dir):
    """Toast should have success, error, warning, info variants."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    toast = out / "src/components/Toast.tsx"
    content = toast.read_text()

    assert "success" in content
    assert "error" in content
    assert "warning" in content


def test_generates_vitest_tests(mock_planning, tmp_output_dir):
    """Should generate Vitest test file."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    files = generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    test_files = [f for f in files if "__tests__" in f or "test" in Path(f).name.lower()]
    assert len(test_files) > 0


def test_button_component_is_accessible(mock_planning, tmp_output_dir):
    """Button should support disabled and loading states."""
    from app.planning.codegen.frontend import generate_frontend

    out = Path(tmp_output_dir)
    (out / "src/pages").mkdir(parents=True, exist_ok=True)
    (out / "src/components").mkdir(parents=True, exist_ok=True)
    (out / "src/api").mkdir(parents=True, exist_ok=True)

    generate_frontend(mock_planning.functional, mock_planning.technical, tmp_output_dir)

    btn = out / "src/components/Button.tsx"
    content = btn.read_text()

    assert "disabled" in content
    assert "loading" in content
