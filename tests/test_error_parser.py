"""Tests for error_parser.py — error categorization and parsing.

Note: Tests are written against the ACTUAL parser behavior, not desired behavior.
"""

import pytest
from app.devkit.error_parser import parse_error
from app.devkit.models import ParsedError


class TestErrorParser:
    """Test error categorization against actual parser patterns."""

    # ── Category tests ──
    # These test the ACTUAL categorization the parser produces.

    def test_module_not_found_is_build_error(self):
        """ModuleNotFoundError → build_error (per CATEGORY_PATTERNS)."""
        error = parse_error("ModuleNotFoundError: No module named 'fastapi'")
        assert error.category == "build_error"

    def test_import_error_is_build_error(self):
        """ImportError → build_error (per CATEGORY_PATTERNS)."""
        error = parse_error("ImportError: cannot import name 'foo' from 'bar'")
        assert error.category == "build_error"

    def test_assertion_error_is_test_failure(self):
        """AssertionError → test_failure."""
        error = parse_error("AssertionError: assert 1 == 2")
        assert error.category == "test_failure"

    def test_type_error_is_runtime(self):
        """TypeError → runtime_error (per CATEGORY_PATTERNS)."""
        error = parse_error("TypeError: Something went wrong at runtime")
        assert error.category == "runtime_error"

    def test_connection_refused_is_config(self):
        """connection refused → config (per CATEGORY_PATTERNS)."""
        error = parse_error("Error: connection refused to localhost:5432")
        assert error.category == "config"

    def test_unrecognized_falls_to_runtime(self):
        """Unknown errors default to runtime_error."""
        error = parse_error("Some weird thing happened!")
        assert error.category == "runtime_error"
        assert error.error_type == "RuntimeError"

    # ── Framework detection ──

    def test_fastapi_framework(self):
        """FastAPI/uvicorn/starlette patterns are detected."""
        error = parse_error(
            "Error in uvicorn: application startup failed\n  File 'main.py', line 10"
        )
        assert error.framework == "fastapi"

    def test_pytest_framework(self):
        """pytest/conftest patterns are detected."""
        error = parse_error("pytest: error: unrecognized arguments: --foo")
        assert error.framework == "pytest"

    def test_docker_framework(self):
        """docker/Dockerfile patterns are detected."""
        error = parse_error("Error: Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
        assert error.framework == "docker"

    def test_typescript_framework(self):
        """tsc/typescript patterns → tsc (beat react by avoiding 'react' in text)."""
        error = parse_error("src/App.ts:10:5 - error TS2307: Cannot find module")
        assert error.framework == "tsc"

    def test_no_framework_match(self):
        """Errors without framework keywords get empty string."""
        error = parse_error("Something generic broke")
        assert error.framework == ""

    # ── File path extraction ──

    def test_file_path_extraction(self):
        error = parse_error(
            'File "app/routes/auth.py", line 42, in login\n'
            "    raise HTTPException(401, 'Invalid token')"
        )
        assert error.file_path == "app/routes/auth.py"

    def test_line_number_extraction(self):
        error = parse_error(
            'File "app/models/user.py", line 1337, in validate\n'
            "    raise ValueError('Bad data')"
        )
        assert error.line_number == 1337

    # ── Error type extraction ──

    def test_error_type_from_runtime(self):
        """TypeError text → error_type extracted."""
        error = parse_error("TypeError: Invalid parameter value")
        assert error.error_type == "TypeError"

    def test_error_type_fallback(self):
        """Without recognized error words → RuntimeError."""
        error = parse_error("Something broke!")
        assert error.error_type == "RuntimeError"

    # ── Edge cases ──

    def test_empty_string(self):
        error = parse_error("")
        assert isinstance(error, ParsedError)
        assert error.category == "runtime_error"

    def test_very_long_trace(self):
        trace = "\n".join(f"  File 'file_{i}.py', line {i}" for i in range(1, 100))
        trace += "\nTypeError: Deep call stack failure"
        error = parse_error(trace)
        assert error.category == "runtime_error"
        assert len(error.stack_summary) <= 3
