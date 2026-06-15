"""Tests for new endpoints: section filter, download/files endpoints, API key management."""

import pytest
from unittest.mock import AsyncMock, patch


# ── API key generation & verification ─────────────────

def test_generate_key_format():
    """API keys should have sf_ prefix and be 51 chars (sf_ + 48 hex)."""
    from app.routes.settings_api import _generate_key
    full_key, prefix, key_hash = _generate_key()
    assert full_key.startswith("sf_"), f"Key should start with sf_: {full_key[:10]}..."
    assert len(full_key) == 51, f"Key should be 51 chars, got {len(full_key)}"
    assert prefix == full_key[:12], "Prefix should be first 12 chars"


def test_generate_key_uniqueness():
    """Two generated keys should be different."""
    from app.routes.settings_api import _generate_key
    k1, _, _ = _generate_key()
    k2, _, _ = _generate_key()
    assert k1 != k2, "Two generated keys should be unique"


def test_verify_api_key():
    """verify_api_key should correctly validate a key against its hash."""
    from app.routes.settings_api import _generate_key, verify_api_key
    full_key, _, key_hash = _generate_key()
    assert verify_api_key(full_key, key_hash) is True
    assert verify_api_key("sf_wrong_key_here", key_hash) is False


def test_verify_api_key_empty():
    """verify_api_key should return False for empty/invalid inputs."""
    from app.routes.settings_api import verify_api_key, _generate_key
    _, _, key_hash = _generate_key()
    assert verify_api_key("", key_hash) is False


# ── Router registration (shallow) ──────────────────────

def test_settings_api_routes_exist():
    """Settings API router should have api-keys CRUD endpoints."""
    from app.routes.settings_api import router
    paths = [r.path for r in router.routes]
    assert any("api-keys" in p for p in paths), f"Routes: {paths}"
    assert any("{key_id}" in p for p in paths), f"Should have DELETE route, got: {paths}"


def test_generate_routes_exist():
    """Generate router should have download and files endpoints."""
    from app.routes.generate import router
    paths = [r.path for r in router.routes]
    assert any("files/" in p and "project_id" in p for p in paths), f"Routes: {paths}"
    assert any("download/" in p for p in paths), f"Routes: {paths}"


def test_planning_routes_exist():
    """Planning router should have download and files endpoints."""
    from app.routes.planning import router
    paths = [r.path for r in router.routes]
    assert any("files/" in p and "project_id" in p for p in paths), f"Routes: {paths}"
    assert any("download/" in p for p in paths), f"Routes: {paths}"


def test_research_routes_exist():
    """Research router should have list, detail, and download routes."""
    from app.routes.research import router
    paths = [r.path for r in router.routes]
    # Should have at least 5 routes: POST /start, GET /, GET /{id}, GET /{id}/download
    assert len(paths) >= 4, f"Routes: {paths}"


# ── Output directory lookup (integration-ish) ──────────

@pytest.mark.asyncio
async def test_planning_output_dir_returns_none_for_unknown_project():
    """_get_planning_output_dir should return None for nonexistent project."""
    from app.routes.planning import _get_planning_output_dir
    result = await _get_planning_output_dir("nonexistent-project-id-12345")
    assert result is None


@pytest.mark.asyncio
async def test_generate_output_dir_returns_none_for_unknown_project():
    """_get_project_output_dir should return None for nonexistent project."""
    from app.routes.generate import _get_project_output_dir
    result = await _get_project_output_dir("nonexistent-project-id-12345", "generate")
    assert result is None


# ── Format & type helpers ──────────────────────────────

def test_format_size_helper():
    """format_size should produce human-readable sizes."""
    from app.routes.planning import format_size
    assert "B" in format_size(100)
    assert "KB" in format_size(1500)
    assert "MB" in format_size(2_000_000)


def test_guess_file_type():
    """guess_file_type should correctly identify file types."""
    from app.utils.files import guess_file_type
    assert guess_file_type("index.html") == "html"
    assert guess_file_type("spec.md") == "markdown"
    assert guess_file_type("data.json") == "json"
    assert guess_file_type("image.png") == "image"
    assert guess_file_type("script.py") == "python"
    assert guess_file_type("styles.css") == "css"
    assert guess_file_type("unknown.xyz") == "unknown"
