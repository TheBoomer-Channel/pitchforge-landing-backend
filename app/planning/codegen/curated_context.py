"""Curated Context — minimal, feature-specific context for codegen subagents.

TASK-066 — Part of Compose Mode CodeGen 3.0.
Each subagent receives only what it needs: no contamination, no overload.
"""

import re
from typing import Optional
from pydantic import BaseModel, Field

from ..models import FeatureAnchor, TechnicalSpec


class CodegenContext(BaseModel):
    """Minimal context for a single feature's code generation.
    
    Follows the MiMo-Code pattern: intent + scope boundaries + curated files.
    """
    intent: str = ""  # "Covers [F1] — User Authentication"
    anchor: str = ""  # "F1"
    
    # Scope curation
    scope_dirs: list[str] = Field(default_factory=list)  # ["app/routes/auth/", "app/models/"]
    do_not_touch: list[str] = Field(default_factory=list)  # ["tests/", "alembic/"]
    
    # Filtered technical context
    relevant_entities: list[dict] = Field(default_factory=list)  # Data model entities
    relevant_endpoints: list[dict] = Field(default_factory=list)  # API endpoints
    
    # Feature specification
    feature_name: str = ""
    feature_description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    
    # Project-wide context (shared, read-only)
    stack_table: list[dict] = Field(default_factory=list)
    project_root: str = ""


def curate_context(
    feature: FeatureAnchor,
    technical: TechnicalSpec,
    project_root: str = "",
) -> CodegenContext:
    """Build a minimal, curated context for a single feature.
    
    Filters the TechnicalSpec to only include entities and endpoints
    relevant to this feature, based on keyword matching.
    """
    # Build keywords from feature name + description
    keywords = _extract_keywords(feature)
    
    # Filter relevant data model entities
    relevant_entities = []
    for entity in (technical.data_model or []):
        entity_name = entity.get("entity", "")
        entity_fields = " ".join(
            f.get("name", "") for f in entity.get("fields", [])
        )
        combined = f"{entity_name} {entity_fields}".lower()
        if any(kw in combined for kw in keywords):
            relevant_entities.append(entity)
    
    # Filter relevant API endpoints
    relevant_endpoints = []
    for ep in (technical.api_endpoints or []):
        path = ep.get("path", "").lower()
        desc = ep.get("description", "").lower()
        combined = f"{path} {desc}"
        if any(kw in combined for kw in keywords):
            relevant_endpoints.append(ep)
    
    # Derive scope directories
    scope_dirs = _derive_scope_dirs(feature, relevant_endpoints)
    do_not_touch = ["tests/", "alembic/", ".github/", "frontend/src/i18n/"]
    
    return CodegenContext(
        intent=f"Covers [{feature.anchor}] — {feature.name}",
        anchor=feature.anchor,
        scope_dirs=scope_dirs,
        do_not_touch=do_not_touch,
        relevant_entities=relevant_entities,
        relevant_endpoints=relevant_endpoints,
        feature_name=feature.name,
        feature_description=feature.description,
        acceptance_criteria=feature.acceptance_criteria,
        stack_table=technical.stack_table or [],
        project_root=project_root,
    )


def _extract_keywords(feature: FeatureAnchor) -> list[str]:
    """Extract searchable keywords from a feature."""
    text = f"{feature.name} {feature.description}".lower()
    # Split on common separators
    words = re.findall(r'[a-z0-9_]{3,}', text)
    # Remove common stop words
    stop = {"the", "and", "for", "with", "that", "this", "from", "user", "users"}
    return [w for w in words if w not in stop]


def _derive_scope_dirs(
    feature: FeatureAnchor,
    endpoints: list[dict],
) -> list[str]:
    """Derive scope directories from feature name and endpoints."""
    dirs = set()
    
    # From endpoints
    for ep in endpoints:
        path = ep.get("path", "")
        # Extract first path segment: /api/research → app/routes/research/
        parts = [p for p in path.strip("/").split("/") if p]
        if parts:
            dirs.add(f"app/routes/{parts[0]}/")
            dirs.add(f"app/models/")
            dirs.add(f"app/schemas/")
    
    # From feature name — only add frontend dirs if feature suggests UI
    name_lower = feature.name.lower().replace(" ", "_")
    ui_keywords = ["ui", "page", "dashboard", "view", "display", "render", "component", "frontend"]
    has_ui = any(kw in feature.name.lower() or kw in feature.description.lower() for kw in ui_keywords)
    
    if has_ui or endpoints:
        dirs.add("frontend/src/pages/")
        dirs.add("frontend/src/components/")
    
    return sorted(dirs)
