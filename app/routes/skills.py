"""Skills API routes — browse and search the builderstudio-skills catalog."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..services.skills_catalog import SkillsCatalog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/list")
async def list_skills(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by name/description/tags"),
):
    """List all skills, optionally filtered by category or search."""
    if search:
        skills = SkillsCatalog.search(search)
        return {"skills": skills, "total": len(skills)}
    if category:
        skills = SkillsCatalog.get_by_category(category)
        return {"skills": skills, "total": len(skills)}
    skills = SkillsCatalog.get_all()
    return {"skills": skills, "total": len(skills)}


@router.get("/categories")
async def list_categories():
    """List all skill categories."""
    return {"categories": SkillsCatalog.get_categories()}


@router.get("/recommend/{area}")
async def recommend_skills(area: str):
    """Get skill recommendations for a specific development area.

    Areas: code_structure, testing, accessibility, design, documentation,
           i18n, infrastructure, api_integration, bugfixing
    """
    VALID_AREAS = [
        "code_structure", "testing", "accessibility", "design",
        "documentation", "i18n", "infrastructure", "api_integration", "bugfixing",
    ]
    if area not in VALID_AREAS:
        raise HTTPException(status_code=404, detail=f"Unknown area: {area}. Valid areas: {', '.join(VALID_AREAS)}")
    skills = SkillsCatalog.recommend_for(area)
    return {"area": area, "skills": skills, "total": len(skills)}


@router.get("/{skill_id}")
async def get_skill(skill_id: str):
    """Get a single skill by ID."""
    skill = SkillsCatalog.get_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return skill
