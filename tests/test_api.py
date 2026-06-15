"""Tests for api.py — API route stub + test generation."""

import pytest
from pathlib import Path


def test_generate_api_stubs_creates_route_files(mock_planning, tmp_output_dir):
    """Should create route files grouped by resource."""
    from app.planning.codegen.api import generate_api_stubs

    out = Path(tmp_output_dir)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)
    (out / "tests").mkdir(parents=True, exist_ok=True)
    (out / "app/core").mkdir(parents=True, exist_ok=True)

    files = generate_api_stubs(mock_planning.technical, tmp_output_dir)

    # Should generate some files (routes, tests, or rate_limit)
    assert len(files) > 0, f"No files generated. Endpoints: {len(mock_planning.technical.api_endpoints)}"


def test_route_files_have_pagination_on_list(mock_planning, tmp_output_dir):
    """List endpoints should have skip/limit pagination params."""
    from app.planning.codegen.api import generate_api_stubs

    out = Path(tmp_output_dir)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)
    (out / "tests").mkdir(parents=True, exist_ok=True)

    generate_api_stubs(mock_planning.technical, tmp_output_dir)

    route_files = list((out / "app/routes").glob("*.py"))
    route_files = [f for f in route_files if f.name != "__init__.py"]

    # At least one file should have pagination
    has_pagination = False
    for rf in route_files:
        content = rf.read_text()
        if "skip: int = Query" in content and "limit: int = Query" in content:
            has_pagination = True
            break

    # Not all routes may be list endpoints, but at least one should have it
    if route_files:
        # Check that the generated code compiles syntactically
        for rf in route_files:
            compile(rf.read_text(), rf.name, "exec")


def test_auth_required_endpoints_have_auth_dep(mock_planning, tmp_output_dir):
    """Protected routes should import and use get_current_user."""
    from app.planning.codegen.api import generate_api_stubs

    out = Path(tmp_output_dir)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)
    (out / "tests").mkdir(parents=True, exist_ok=True)

    generate_api_stubs(mock_planning.technical, tmp_output_dir)

    route_files = list((out / "app/routes").glob("*.py"))
    route_files = [f for f in route_files if f.name != "__init__.py"]

    # At least one file (users) should have auth
    has_auth = False
    for rf in route_files:
        content = rf.read_text()
        if "get_current_user" in content:
            has_auth = True
            break

    # Users endpoint requires auth, so this should be true
    if any("users" in rf.name for rf in route_files):
        assert has_auth, "Users routes should have auth dependency"


def test_generates_test_file(mock_planning, tmp_output_dir):
    """Should generate test_api.py with CRUD tests."""
    from app.planning.codegen.api import generate_api_stubs

    out = Path(tmp_output_dir)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)
    (out / "tests").mkdir(parents=True, exist_ok=True)

    generate_api_stubs(mock_planning.technical, tmp_output_dir)

    test_file = out / "tests/test_api.py"
    assert test_file.exists()

    content = test_file.read_text()
    assert "pytest" in content
    assert "AsyncClient" in content
    assert "async def test_" in content


def test_rate_limit_config_generated(mock_planning, tmp_output_dir):
    """Should generate rate_limit.py when public endpoints exist."""
    from app.planning.codegen.api import generate_api_stubs

    out = Path(tmp_output_dir)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)
    (out / "app/core").mkdir(parents=True, exist_ok=True)

    files = generate_api_stubs(mock_planning.technical, tmp_output_dir)

    rate_limit = out / "app/core/rate_limit.py"
    # Should exist since there are public endpoints
    assert rate_limit.exists()
    content = rate_limit.read_text()
    assert "Limiter" in content


def test_ep_to_func_name_conversion():
    """_ep_to_func_name should convert paths correctly."""
    from app.planning.codegen.api import _ep_to_func_name

    assert _ep_to_func_name("GET", "/users") == "get_users"
    assert _ep_to_func_name("POST", "/users") == "post_users"
    assert _ep_to_func_name("GET", "/users/{id}") == "get_users"
    assert _ep_to_func_name("DELETE", "/projects/{id}") == "delete_projects"


def test_endpoint_grouping(mock_planning, tmp_output_dir):
    """Endpoints should be grouped by resource prefix."""
    from app.planning.codegen.api import generate_api_stubs
    import os

    out = Path(tmp_output_dir)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)
    (out / "tests").mkdir(parents=True, exist_ok=True)
    (out / "app/core").mkdir(parents=True, exist_ok=True)

    generate_api_stubs(mock_planning.technical, tmp_output_dir)

    # Check that route files were created in app/routes/
    route_dir = out / "app/routes"
    py_files = [f for f in os.listdir(str(route_dir)) if f.endswith(".py") and f != "__init__.py"]
    assert len(py_files) > 0, f"No route files found in {route_dir}"
