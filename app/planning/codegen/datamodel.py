"""Data model codegen — entities → SQLModel models + Pydantic schemas + CRUD routes."""

import logging
from pathlib import Path

from ..models import TechnicalSpec

logger = logging.getLogger(__name__)


TYPE_MAP = {
    "str": "str",
    "string": "str",
    "int": "int",
    "integer": "int",
    "float": "float",
    "bool": "bool",
    "boolean": "bool",
    "datetime": "datetime",
    "date": "date",
    "text": "str",
    "email": "str",
    "url": "str",
    "uuid": "str",
    "json": "dict",
    "phone": "str",
    "enum": "str",
    "decimal": "float",
    "relation": "int",  # FK
}

# ── Base Mixins ───────────────────────────────────────

TIMESTAMP_MIXIN = """
class TimestampMixin(SQLModel):
    \"\"\"Adds created_at and updated_at to any model.\"\"\"
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )
"""

SOFT_DELETE_MIXIN = """
class SoftDeleteMixin(SQLModel):
    \"\"\"Soft delete support — marks as deleted instead of removing.\"\"\"
    is_deleted: bool = Field(default=False)
    deleted_at: Optional[datetime] = Field(default=None)
"""



def generate_models(tech: TechnicalSpec, output_dir: str) -> list[str]:
    """Generate SQLModel models from data_model specs."""
    out = Path(output_dir)
    models_init = out / "app/models/__init__.py"
    schemas_init = out / "app/schemas/__init__.py"

    generated_files = []

    entities = tech.data_model or []
    if not entities:
        # Use API endpoints to infer entities
        entities = _infer_entities_from_api(tech.api_endpoints)

    if not entities:
        logger.warning("No data model entities found — generating User-only scaffold")
        entities = [{
            "entity": "User",
            "fields": [
                {"name": "id", "type": "int", "notes": "PK auto"},
                {"name": "email", "type": "str", "notes": "unique"},
                {"name": "name", "type": "str"},
                {"name": "is_active", "type": "bool", "notes": "default true"},
            ],
            "relations": [],
        }]

    model_imports = []
    schema_imports = []
    router_imports = []
    model_classes = []
    schema_classes = []
    router_functions = []
    has_timestamps = True
    has_softdelete = any("soft" in str(f.get("notes", "")).lower() or "deleted_at" in str(f.get("name", "")).lower() for e in entities for f in e.get("fields", []))
    
    crud_imports = """from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime
"""
    if has_timestamps:
        crud_imports += TIMESTAMP_MIXIN + "\n"
    if has_softdelete:
        crud_imports += SOFT_DELETE_MIXIN + "\n"
    
    schema_import_lines = "from pydantic import BaseModel, EmailStr\nfrom typing import Optional\nfrom datetime import datetime\n"

    for entity in entities:
        name = entity.get("entity", "Entity")
        fields = entity.get("fields", [])
        relations = entity.get("relations", [])
        snake = _to_snake(name)
        table_name = _to_table(name)

        # ── Model ──
        model_lines = [f"class {name}(SQLModel, table=True):"]
        model_lines.append(f"    __tablename__ = \"{table_name}\"")
        model_lines.append("")
        pk_field = None
        for f in fields:
            fname = f.get("name", "id")
            ftype = TYPE_MAP.get(f.get("type", "str").lower(), "str")
            notes = f.get("notes", "")
            is_pk = "pk" in notes.lower() or fname == "id"
            is_unique = "unique" in notes.lower()
            nullable = "optional" in notes.lower() or "nullable" in notes.lower()
            fdef = f"    {fname}: {ftype}"
            if nullable or fname == "id":
                fdef = f"    {fname}: Optional[{ftype}]"
            if is_pk:
                fdef += f" = Field(default=None, primary_key=True"
                if "auto" in notes.lower():
                    fdef += ', sa_column_kwargs={"autoincrement": True}'
            elif is_unique:
                fdef += f" = Field(default=None, unique=True"
            elif ftype == "bool":
                fdef += f" = Field(default=True"
            else:
                fdef += f" = Field(default=None"
            if nullable:
                fdef += ", nullable=True"
            fdef += ")"
            model_lines.append(fdef)

        for rel in relations:
            parts = rel.split(":")
            if len(parts) == 2:
                rel_type = parts[0].strip()
                target = parts[1].strip()
                if rel_type.lower() in ("hasmany", "has_many"):
                    model_lines.append(f"    {_to_snake(target)}s: list[\"{target}\"] = Relationship(back_populates=\"{_to_snake(name)}\")")
                elif rel_type.lower() == "belongsto" or rel_type.lower() == "belongs_to":
                    model_lines.append(f"    {_to_snake(target)}_id: Optional[int] = Field(default=None, foreign_key=\"{_to_table(target)}.id\")")
                    model_lines.append(f"    {_to_snake(target)}: Optional[\"{target}\"] = Relationship(back_populates=\"{_to_snake(name)}s\")")

        model_lines.append("")
        model_classes.append("\n".join(model_lines))
        model_imports.append(name)

        # ── Schema ──
        schema_lines = [f"class {name}Create(BaseModel):"]
        for f in fields:
            fname = f.get("name", "")
            if fname == "id" or "pk" in f.get("notes", "").lower():
                continue
            ftype = TYPE_MAP.get(f.get("type", "str").lower(), "str")
            notes = f.get("notes", "")
            optional = "optional" in notes.lower() or "nullable" in notes.lower()
            ext = " = None" if optional else ""
            schema_lines.append(f"    {fname}: {ftype}{ext}")

        schema_lines.append("")
        schema_lines.append(f"class {name}Read(BaseModel):")
        schema_lines.append(f"    id: int")
        for f in fields:
            fname = f.get("name", "")
            if fname == "id":
                continue
            ftype = TYPE_MAP.get(f.get("type", "str").lower(), "str")
            schema_lines.append(f"    {fname}: {ftype}")

        schema_lines.append("")
        schema_lines.append(f"class {name}Update(BaseModel):")
        for f in fields:
            fname = f.get("name", "")
            if fname == "id":
                continue
            ftype = TYPE_MAP.get(f.get("type", "str").lower(), "str")
            schema_lines.append(f"    {fname}: Optional[{ftype}] = None")

        schema_classes.append("\n".join(schema_lines))
        schema_imports.append(name)

        # ── CRUD Router ──
        router_lines = [
            f"from fastapi import APIRouter, Depends, HTTPException",
            f"from sqlalchemy.ext.asyncio import AsyncSession",
            f"from sqlalchemy import select",
            f"from app.database import get_session",
            f"from app.models.{snake} import {name}",
            f"from app.schemas.{snake} import {name}Create, {name}Read, {name}Update",
            "",
            f"router = APIRouter(prefix=\"/{_to_route(name)}\", tags=[\"{name}\"])",
            "",
            f"@router.get(\"/\", response_model=list[{name}Read])",
            f"async def list_{snake}s(session: AsyncSession = Depends(get_session)):",
            f"    result = await session.execute(select({name}))",
            f"    return result.scalars().all()",
            "",
            f"@router.get(\"/{{{snake}_id}}\", response_model={name}Read)",
            f"async def get_{snake}({snake}_id: int, session: AsyncSession = Depends(get_session)):",
            f"    obj = await session.get({name}, {snake}_id)",
            f"    if not obj:",
            f"        raise HTTPException(404, detail=\"{name} not found\")",
            f"    return obj",
            "",
            f"@router.post(\"/\", response_model={name}Read, status_code=201)",
            f"async def create_{snake}(data: {name}Create, session: AsyncSession = Depends(get_session)):",
            f"    obj = {name}(**data.model_dump())",
            f"    session.add(obj)",
            f"    await session.commit()",
            f"    await session.refresh(obj)",
            f"    return obj",
            "",
            f"@router.patch(\"/{{{snake}_id}}\", response_model={name}Read)",
            f"async def update_{snake}({snake}_id: int, data: {name}Update, session: AsyncSession = Depends(get_session)):",
            f"    obj = await session.get({name}, {snake}_id)",
            f"    if not obj:",
            f"        raise HTTPException(404, detail=\"{name} not found\")",
            f"    for key, val in data.model_dump(exclude_unset=True).items():",
            f"        setattr(obj, key, val)",
            f"    session.add(obj)",
            f"    await session.commit()",
            f"    await session.refresh(obj)",
            f"    return obj",
            "",
            f"@router.delete(\"/{{{snake}_id}}\", status_code=204)",
            f"async def delete_{snake}({snake}_id: int, session: AsyncSession = Depends(get_session)):",
            f"    obj = await session.get({name}, {snake}_id)",
            f"    if not obj:",
            f"        raise HTTPException(404, detail=\"{name} not found\")",
            f"    await session.delete(obj)",
            f"    await session.commit()",
        ]
        router_functions.append((snake, "\n".join(router_lines)))
        router_imports.append(name)

    # Write model files
    for entity in entities:
        name = entity.get("entity", "Entity")
        snake = _to_snake(name)
        # Find the matching model class
        model_code = ""
        for mc in model_classes:
            if mc.startswith(f"class {name}("):
                model_code = mc
                break
        if model_code:
            p = out / f"app/models/{snake}.py"
            p.write_text(crud_imports + "\n" + model_code)
            generated_files.append(str(p))

        # Schema files
        schema_code = ""
        for sc in schema_classes:
            if sc.startswith(f"class {name}Create"):
                schema_code = sc
                # Also collect Read and Update
                for sc2 in schema_classes:
                    if sc2.startswith(f"class {name}Read") or sc2.startswith(f"class {name}Update"):
                        schema_code += "\n\n" + sc2
                break
        if schema_code:
            p = out / f"app/schemas/{snake}.py"
            p.write_text(schema_import_lines + "\n" + schema_code)
            generated_files.append(str(p))

        # Router files
        for rsnake, rcode in router_functions:
            if rsnake == snake:
                p = out / f"app/routes/{snake}.py"
                p.write_text(rcode)
                generated_files.append(str(p))
                break

    # Write __init__.py files
    models_init_content = "from sqlmodel import SQLModel\n"
    for entity in entities:
        name = entity.get("entity", "Entity")
        snake = _to_snake(name)
        models_init_content += f"from .{snake} import {name}\n"
    models_init.write_text(models_init_content)
    generated_files.append(str(models_init))

    schemas_init_content = ""
    for entity in entities:
        name = entity.get("entity", "Entity")
        snake = _to_snake(name)
        schemas_init_content += f"from .{snake} import {name}Create, {name}Read, {name}Update\n"
    schemas_init.write_text(schemas_init_content)
    generated_files.append(str(schemas_init))

    # Write routes __init__
    routes_init = out / "app/routes/__init__.py"
    routes_imports = "from fastapi import APIRouter\n\nrouter = APIRouter()\n"
    for entity in entities:
        name = entity.get("entity", "Entity")
        snake = _to_snake(name)
        routes_imports += f"from .{snake} import router as {snake}_router\n"
        routes_imports += f"router.include_router({snake}_router)\n"
    routes_init.write_text(routes_imports)
    generated_files.append(str(routes_init))

    return generated_files


def _infer_entities_from_api(endpoints: list[dict]) -> list[dict]:
    """Infer data model entities from API endpoint paths."""
    entities = {}
    for ep in endpoints:
        path = ep.get("path", "")
        parts = path.strip("/").split("/")
        for part in parts:
            if part and not part.startswith("{") and not part.startswith("api"):
                name = part.rstrip("s").capitalize()
                if name not in entities:
                    entities[name] = {"entity": name, "fields": [
                        {"name": "id", "type": "int", "notes": "PK auto"},
                        {"name": "name", "type": "str", "notes": ""},
                        {"name": "is_active", "type": "bool", "notes": "default true"},
                    ], "relations": []}
    return list(entities.values())


def _to_snake(name: str) -> str:
    import re
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return s


def _to_table(name: str) -> str:
    return _to_snake(name) + "s"


def _to_route(name: str) -> str:
    return _to_snake(name).replace("_", "-")
