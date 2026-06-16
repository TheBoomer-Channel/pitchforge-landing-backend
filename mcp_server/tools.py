"""MCP Tool implementations — wraps PitchForge API calls as MCP tools.

Each tool function:
- Receives typed parameters from the MCP server
- Calls the PitchForge API or internal services
- Returns a formatted text result for the LLM

This module follows the same pattern as the routes — using existing Services
(research_runner, generator, projects) instead of duplicating business logic.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────

API_BASE_URL = os.getenv("PITCHFORGE_API_URL", "http://api:8086")
INTERNAL_API_KEY = os.getenv("MCP_API_KEY", "")


async def _api_post(path: str, payload: dict) -> dict:
    """Make an internal API request to the PitchForge backend.

    Uses X-API-Key header matching the API's auth middleware pattern.
    The API middleware checks X-API-Key first, then Authorization: Bearer sf_...
    """
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_KEY:
        headers["X-API-Key"] = INTERNAL_API_KEY

    async with httpx.AsyncClient(
        base_url=API_BASE_URL,
        timeout=httpx.Timeout(300, connect=10.0),
    ) as client:
        resp = await client.post(path, json=payload, headers=headers)
        if resp.status_code >= 400:
            error_detail = resp.text[:500]
            raise RuntimeError(f"API error {resp.status_code}: {error_detail}")
        return resp.json()


async def _api_get(path: str) -> dict:
    """Make an internal GET request to the PitchForge backend.

    Uses X-API-Key header matching the API's auth middleware pattern.
    """
    headers = {}
    if INTERNAL_API_KEY:
        headers["X-API-Key"] = INTERNAL_API_KEY

    async with httpx.AsyncClient(
        base_url=API_BASE_URL,
        timeout=httpx.Timeout(30, connect=10.0),
    ) as client:
        resp = await client.get(path, headers=headers)
        if resp.status_code >= 400:
            error_detail = resp.text[:500]
            raise RuntimeError(f"API error {resp.status_code}: {error_detail}")
        return resp.json()


# ── Tool Implementations ───────────────────────────────


async def research_idea(
    idea: str,
    target_market: Optional[str] = None,
    business_model: Optional[str] = None,
) -> str:
    """Run full market research on a startup idea.

    Calls the same ResearchEngine used by the web API.
    """
    if not idea or len(idea) < 10:
        return "Error: Idea must be at least 10 characters."

    logger.info(f"MCP: research_idea('{idea[:60]}')")

    try:
        payload = {
            "idea": idea.strip(),
            "target_market": target_market or "",
            "business_model": business_model or "",
        }
        result = await _api_post("/api/research/start", payload)

        # Format a concise summary for the LLM
        report = result
        summary = report.get("summary", "")
        competitors = report.get("competitors", [])
        features = report.get("recommended_mvp_features", [])

        lines = [
            f"# Research: {idea}",
            "",
            f"**Summary:** {summary[:500] if summary else 'N/A'}",
            "",
            f"**Competitors ({len(competitors)} found):**",
        ]
        for c in competitors[:8]:
            name = c.get("name", "?")
            desc = c.get("description", "")[:120]
            pricing = c.get("pricing", "")
            lines.append(f"- {name}: {desc} {'| Pricing: ' + pricing if pricing else ''}")
        lines.append("")

        if features:
            lines.append(f"**Recommended MVP Features ({len(features)}):**")
            for f in features:
                lines.append(f"- {f}")

        lines.append("")
        lines.append("---")
        lines.append(f"*Research complete — generated at {datetime.now().isoformat()}*")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"MCP research failed: {e}", exc_info=True)
        return f"Research failed: {e}"


async def generate_assets(
    idea: str,
    types: Optional[list[str]] = None,
) -> str:
    """Generate pitch deck, landing page, and/or pricing page HTML."""
    if not idea or len(idea) < 10:
        return "Error: Idea must be at least 10 characters."

    types = types or ["pitch", "landing", "pricing"]
    logger.info(f"MCP: generate_assets('{idea[:60]}', types={types})")

    try:
        result = await _api_post("/api/generate", {
            "idea": idea.strip(),
            "types": types,
        })

        generated = result.get("generated", {})
        lines = [f"# Generated Assets: {idea}", ""]

        for asset_type in types:
            info = generated.get(asset_type, {})
            path = info.get("path", "N/A")
            size = info.get("size_bytes", 0)
            lines.append(f"**{asset_type.title()}:** {path} ({size} bytes)")

        lines.append("")
        lines.append("---")
        lines.append(f"*Assets generated at {datetime.now().isoformat()}*")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"MCP generate failed: {e}", exc_info=True)
        return f"Asset generation failed: {e}"


async def analyze_competitors(idea: str) -> str:
    """Extract structured competitive analysis."""
    if not idea or len(idea) < 10:
        return "Error: Idea must be at least 10 characters."

    logger.info(f"MCP: analyze_competitors('{idea[:60]}')")

    try:
        # Research first, then extract competitive insights
        research_result = await _api_post("/api/research/start", {
            "idea": idea.strip(),
            "target_market": "",
            "business_model": "",
        })

        competitors = research_result.get("competitors", [])
        gaps = research_result.get("opportunity_gaps", [])
        insights = research_result.get("competitive_insights", {})

        lines = [f"# Competitive Analysis: {idea}", ""]

        if insights:
            # Table stakes
            table_stakes = insights.get("must_have_features", {}).get("table_stakes", [])
            if table_stakes:
                lines.append("## Table Stakes (features ALL competitors have)")
                for f in table_stakes:
                    lines.append(f"- ✅ {f}")

            # Differentiators
            differentiators = insights.get("must_have_features", {}).get("differentiators", [])
            if differentiators:
                lines.append("\n## Differentiation Gaps (opportunities)")
                for f in differentiators:
                    lines.append(f"- 🚀 {f}")

            # Pain points
            pain_summary = insights.get("pain_summary", {})
            critical = pain_summary.get("critical", [])
            common = pain_summary.get("common", [])
            if critical:
                lines.append(f"\n## Critical Pain Points")
                for p in critical:
                    lines.append(f"- 🔴 {p}")
            if common:
                lines.append(f"\n## Common Pain Points")
                for p in common:
                    lines.append(f"- 🟡 {p}")

            # Pricing landscape
            pricing = insights.get("pricing_landscape", {})
            if pricing.get("range"):
                r = pricing["range"]
                lines.append(f"\n## Pricing Landscape")
                lines.append(f"- Range: ${r.get('min', 0)} - ${r.get('max', 0)}")
                lines.append(f"- Median: ${r.get('median', 0)}")
                lines.append(f"- Free tier available: {pricing.get('free_tier_available', False)}")

        lines.append(f"\n## Competitors ({len(competitors)} total)")
        for c in competitors[:5]:
            name = c.get("name", "?")
            desc = c.get("description", "")[:200]
            strengths = c.get("strengths", [])
            weaknesses = c.get("weaknesses", [])
            lines.append(f"\n### {name}")
            lines.append(f"  {desc}")
            if strengths:
                lines.append(f"  💪 Strengths: {', '.join(strengths[:3])}")
            if weaknesses:
                lines.append(f"  🪨 Weaknesses: {', '.join(weaknesses[:3])}")

        if gaps:
            lines.append(f"\n## Opportunity Gaps ({len(gaps)} found)")
            for g in gaps:
                lines.append(f"- **{g.get('gap', '')}** (severity: {g.get('severity', 'N/A')})")

        lines.append("\n---")
        lines.append(f"*Analysis generated at {datetime.now().isoformat()}*")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"MCP analysis failed: {e}", exc_info=True)
        return f"Competitor analysis failed: {e}"


async def check_project_status(project_id: str) -> str:
    """Check the status of a project."""
    if not project_id:
        return "Error: project_id is required."

    logger.info(f"MCP: check_project_status('{project_id[:12]}')")

    try:
        result = await _api_get(f"/api/projects/{project_id}/state")

        lines = [
            f"# Project Status: {result.get('title', project_id[:12])}",
            "",
            f"**Status:** {result.get('status', 'unknown')}",
            f"**Pipeline:**",
        ]
        pipeline = result.get("pipeline", {})
        for step, state in pipeline.items():
            status = state.get("status", "pending")
            icon = {"complete": "✅", "running": "🔄", "error": "❌", "pending": "⏳"}
            lines.append(f"  {icon.get(status, '⏳')} {step}: {status}")

        return "\n".join(lines)

    except Exception as e:
        return f"Failed to check project status: {e}"


async def health_check() -> str:
    """Check MCP server and API health."""
    try:
        api_result = await _api_get("/health")
        api_status = api_result.get("status", "unknown")
        db_status = api_result.get("components", {}).get("database", {}).get("status", "?")
    except Exception as e:
        api_status = f"API unreachable: {e}"
        db_status = "?"

    lines = [
        "# PitchForge Health Check",
        "",
        f"**MCP Server:** ✅ Running (v0.1.0)",
        f"**API Status:** {'✅' if api_status == 'ok' else '❌'} {api_status}",
        f"**Database:** {db_status}",
        "",
        "**Available Tools:**",
        "- `research_idea` — Full market research",
        "- `generate_assets` — Pitch deck, landing page, pricing page",
        "- `analyze_competitors` — Structured competitive analysis",
        "- `check_project_status` — Project pipeline status",
        "- `health_check` — Server health",
    ]
    return "\n".join(lines)
