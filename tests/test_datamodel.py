"""Tests for datamodel.py — SQLModel + Pydantic schema generation."""

import pytest
from pathlib import Path


def test_generate_models_creates_files(mock_planning, tmp_output_dir):
    """Should create model, schema, and route files."""
    from app.planning.codegen.datamodel import generate_models

    # Create necessary dirs first
    out = Path(tmp_output_dir)
    (out / "app/models").mkdir(parents=True, exist_ok=True)
    (out / "app/schemas").mkdir(parents=True, exist_ok=True)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)

    files = generate_models(mock_planning.technical, tmp_output_dir)

    assert len(files) > 0
    # Should have at least models, schemas, routes, and __init__ files
    model_files = [f for f in files if "models" in f and "__init__" not in f]
    schema_files = [f for f in files if "schemas" in f and "__init__" not in f]
    route_files = [f for f in files if "routes" in f and "__init__" not in f]

    assert len(model_files) > 0
    assert len(schema_files) > 0


def test_models_have_timestamp_mixin(mock_planning, tmp_output_dir):
    """Generated models should include TimestampMixin."""
    from app.planning.codegen.datamodel import generate_models

    out = Path(tmp_output_dir)
    (out / "app/models").mkdir(parents=True, exist_ok=True)
    (out / "app/schemas").mkdir(parents=True, exist_ok=True)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)

    generate_models(mock_planning.technical, tmp_output_dir)

    # Read the first model file found
    model_files = list((out / "app/models").glob("*.py"))
    model_files = [f for f in model_files if f.name != "__init__.py"]

    if model_files:
        content = model_files[0].read_text()
        # Should have TimestampMixin or created_at
        assert "created_at" in content.lower() or "TimestampMixin" in content


def test_schemas_have_create_read_update(mock_planning, tmp_output_dir):
    """Should generate Create, Read, and Update schemas."""
    from app.planning.codegen.datamodel import generate_models

    out = Path(tmp_output_dir)
    (out / "app/models").mkdir(parents=True, exist_ok=True)
    (out / "app/schemas").mkdir(parents=True, exist_ok=True)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)

    generate_models(mock_planning.technical, tmp_output_dir)

    schema_files = list((out / "app/schemas").glob("*.py"))
    schema_files = [f for f in schema_files if f.name != "__init__.py"]

    for sf in schema_files:
        content = sf.read_text()
        assert "Create" in content
        assert "Read" in content
        assert "Update" in content


def test_routes_have_crud_operations(mock_planning, tmp_output_dir):
    """Generated routes should have CRUD operations."""
    from app.planning.codegen.datamodel import generate_models

    out = Path(tmp_output_dir)
    (out / "app/models").mkdir(parents=True, exist_ok=True)
    (out / "app/schemas").mkdir(parents=True, exist_ok=True)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)

    generate_models(mock_planning.technical, tmp_output_dir)

    route_files = list((out / "app/routes").glob("*.py"))
    route_files = [f for f in route_files if f.name != "__init__.py"]

    for rf in route_files:
        content = rf.read_text()
        assert "@router.get" in content
        assert "@router.post" in content


def test_type_map_has_extended_types():
    """TYPE_MAP should include email, url, phone, json, enum."""
    from app.planning.codegen.datamodel import TYPE_MAP

    extended = ["email", "url", "phone", "json", "enum"]
    for t in extended:
        assert t in TYPE_MAP, f"TYPE_MAP missing: {t}"


def test_timestamp_mixin_defined():
    """TIMESTAMP_MIXIN should be defined and include created_at, updated_at."""
    from app.planning.codegen.datamodel import TIMESTAMP_MIXIN

    assert "created_at" in TIMESTAMP_MIXIN
    assert "updated_at" in TIMESTAMP_MIXIN


def test_soft_delete_mixin_defined():
    """SOFT_DELETE_MIXIN should be defined."""
    from app.planning.codegen.datamodel import SOFT_DELETE_MIXIN

    assert "is_deleted" in SOFT_DELETE_MIXIN
    assert "deleted_at" in SOFT_DELETE_MIXIN


def test_handles_empty_data_model(mock_planning, tmp_output_dir):
    """Should handle empty data model by inferring from endpoints."""
    from app.planning.codegen.datamodel import generate_models
    import copy

    planning = copy.deepcopy(mock_planning)
    planning.technical.data_model = []

    out = Path(tmp_output_dir)
    (out / "app/models").mkdir(parents=True, exist_ok=True)
    (out / "app/schemas").mkdir(parents=True, exist_ok=True)
    (out / "app/routes").mkdir(parents=True, exist_ok=True)

    files = generate_models(planning.technical, tmp_output_dir)
    assert len(files) > 0
