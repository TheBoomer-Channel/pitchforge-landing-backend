"""PitchForge MCP Server — Model Context Protocol for Claude/Cursor/Tools.

TASK-055 — MCP Server nativo.

Usage:
    # Start the server (stdio transport for Claude Desktop)
    python -m mcp_server.server

    # Or as an ASGI app via SSE
    python -m mcp_server.server --transport sse --port 8087

Tools:
    - search_reddit: Search Reddit for startup idea validation
    - search_hn: Search Hacker News for tech community signal
    - search_research: Full multi-source research pipeline
    - generate_pitch: Generate HTML pitch deck from research
    - estimate_pricing: Generate pricing page from research data
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Add backend root to path for imports
_backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_root))

from dotenv import load_dotenv

# Load .env
_env_path = _backend_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# ── MCP imports (validated at module load) ─────────────

try:
    from mcp.server import Server
    from mcp.server.models import InitializationOptions
    import mcp.server.stdio
    import mcp.types as types
except ImportError as _mcp_err:
    Server = None  # type: ignore
    InitializationOptions = None  # type: ignore
    mcp = None  # type: ignore
    types = None  # type: ignore
    _mcp_import_error = str(_mcp_err)
else:
    _mcp_import_error = None

# ── Logging ────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp-server")


# ── Auth ───────────────────────────────────────────────

MCP_API_KEY = os.getenv("MCP_API_KEY", os.getenv("API_KEY", ""))


def verify_auth(api_key: str) -> bool:
    """Verify API key for MCP access."""
    if not MCP_API_KEY:
        return True  # No auth configured — allow all (dev mode)
    return api_key == MCP_API_KEY


# ── Tool Implementations ──────────────────────────────

async def search_reddit(query: str, target_market: str = "") -> str:
    """Search Reddit for community sentiment about a startup idea.

    Args:
        query: The startup idea or topic to research on Reddit.
        target_market: Optional target market/industry context.

    Returns:
        JSON string with Reddit results including top posts, sentiment, complaints.
    """
    try:
        from app.research.sources.reddit_source import RedditSource
        from app.research.http_client import ResearchHTTPClient

        http_client = ResearchHTTPClient()
        source = RedditSource(http_client=http_client)

        result = await source.search(query, context={"target_market": target_market})
        await source.close()

        return json.dumps({
            "success": result.success,
            "posts_found": result.raw_metadata.get("posts_found", 0),
            "sentiment": result.raw_metadata.get("sentiment"),
            "common_complaints": result.raw_metadata.get("common_complaints", [])[:5],
            "common_desires": result.raw_metadata.get("common_desires", [])[:5],
            "top_posts": result.raw_metadata.get("top_posts", [])[:5],
            "blocked": result.raw_metadata.get("blocked", False),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


async def search_hn(query: str) -> str:
    """Search Hacker News for tech community signal about a startup idea.

    Args:
        query: The startup idea or topic to research on Hacker News.

    Returns:
        JSON string with HN results including mentions, points, top stories.
    """
    try:
        from app.research.sources.hn_source import HackerNewsSource
        from app.research.http_client import ResearchHTTPClient

        http_client = ResearchHTTPClient()
        source = HackerNewsSource(http_client=http_client)

        result = await source.search(query)
        await source.close()

        return json.dumps({
            "success": result.success,
            "mentions": result.raw_metadata.get("mentions", 0),
            "total_points": result.raw_metadata.get("total_points", 0),
            "signal_level": result.raw_metadata.get("signal_level"),
            "top_posts": result.raw_metadata.get("top_posts", [])[:5],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


async def search_research(
    idea: str,
    target_market: str = "",
    business_model: str = "",
) -> str:
    """Run full multi-source research on a startup idea.

    Uses all enabled research sources (Tavily, Perplexity, Reddit, HN,
    GitHub, Wikipedia, Brave, DuckDuckGo) and synthesizes a report.

    Args:
        idea: The startup idea to research.
        target_market: Optional target market/industry.
        business_model: Optional business model description.

    Returns:
        JSON string with the full ResearchReport.
    """
    try:
        from app.services.research_runner import run_inline_research

        report = await run_inline_research(
            idea=idea,
            target_market=target_market,
            business_model=business_model,
        )

        return json.dumps({
            "success": True,
            "summary": report.summary,
            "competitors": [
                {"name": c.name, "description": c.description[:200]}
                for c in (report.competitors or [])
            ],
            "market_validation": report.market_validation.model_dump(mode="json") if report.market_validation else None,
            "opportunity_gaps": [g.gap for g in (report.opportunity_gaps or [])],
            "recommended_mvp_features": report.recommended_mvp_features,
            "recommended_pricing_range": report.recommended_pricing_range,
            "recommended_positioning": report.recommended_positioning,
            "risk_factors": report.risk_factors,
            "sources_used": report.sources_used,
            "research_duration_ms": report.research_duration_ms,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


async def generate_pitch(idea: str, target_market: str = "", business_model: str = "") -> str:
    """Generate a complete HTML pitch deck for a startup idea.

    First runs research on the idea, then generates a pitch deck with
    narrative slides, speaker notes, and market analysis.

    Args:
        idea: The startup idea for the pitch deck.
        target_market: Optional target market/industry.
        business_model: Optional business model description.

    Returns:
        JSON string with the generated pitch deck HTML and metadata.
    """
    try:
        from app.services.research_runner import run_inline_research
        from app.generator.pitch import build_pitch_html
        from app.generator.narrative import generate_narrative

        report = await run_inline_research(
            idea=idea,
            target_market=target_market,
            business_model=business_model,
        )

        narrative = generate_narrative(report)
        html = build_pitch_html(report, narrative=narrative)

        return json.dumps({
            "success": True,
            "html": html,
            "slides": narrative.total_slides,
            "title": report.idea[:80],
            "summary": report.summary[:500],
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


async def estimate_pricing(idea: str, target_market: str = "", business_model: str = "") -> str:
    """Generate a pricing page from research data.

    Analyzes competitors and market data to suggest optimal pricing tiers.

    Args:
        idea: The startup idea for pricing estimation.
        target_market: Optional target market/industry.
        business_model: Optional business model description.

    Returns:
        JSON string with the generated pricing HTML and tier data.
    """
    try:
        from app.services.research_runner import run_inline_research
        from app.generator.pricing import build_pricing_html

        report = await run_inline_research(
            idea=idea,
            target_market=target_market,
            business_model=business_model,
        )

        html = build_pricing_html(report)

        return json.dumps({
            "success": True,
            "html": html,
            "recommended_pricing": report.recommended_pricing_range,
            "competitors_analyzed": len(report.competitors or []),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


# ── MCP Server Definition ─────────────────────────────

def create_mcp_server():
    """Create and configure the MCP server with all tools."""
    if Server is None:
        logger.error(
            f"mcp package not installed ({_mcp_import_error}). Run: pip install mcp"
        )
        sys.exit(1)

    server = Server("pitchforge-mcp")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List all available PitchForge tools."""
        return [
            types.Tool(
                name="search_reddit",
                description="Search Reddit for community sentiment, pain points, and desires about a startup idea",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The startup idea or topic to research on Reddit",
                        },
                        "target_market": {
                            "type": "string",
                            "description": "Optional target market/industry context",
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="search_hn",
                description="Search Hacker News for tech community signal, interest level, and top stories about an idea",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The startup idea or topic to research on HN",
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="search_research",
                description="Run full multi-source research (Tavily, Reddit, HN, GitHub, web) on a startup idea",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "idea": {
                            "type": "string",
                            "description": "The startup idea to research",
                        },
                        "target_market": {
                            "type": "string",
                            "description": "Optional target market/industry",
                        },
                        "business_model": {
                            "type": "string",
                            "description": "Optional business model description",
                        },
                    },
                    "required": ["idea"],
                },
            ),
            types.Tool(
                name="generate_pitch",
                description="Generate a complete HTML pitch deck with narrative slides for a startup idea",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "idea": {
                            "type": "string",
                            "description": "The startup idea for the pitch deck",
                        },
                        "target_market": {
                            "type": "string",
                            "description": "Optional target market/industry",
                        },
                        "business_model": {
                            "type": "string",
                            "description": "Optional business model description",
                        },
                    },
                    "required": ["idea"],
                },
            ),
            types.Tool(
                name="estimate_pricing",
                description="Generate a pricing page with competitor analysis and recommended tiers",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "idea": {
                            "type": "string",
                            "description": "The startup idea for pricing estimation",
                        },
                        "target_market": {
                            "type": "string",
                            "description": "Optional target market/industry",
                        },
                        "business_model": {
                            "type": "string",
                            "description": "Optional business model description",
                        },
                    },
                    "required": ["idea"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent]:
        """Execute a PitchForge tool."""
        logger.info(f"Tool called: {name} with args={arguments}")

        # Auth: accept api_key from arguments or rely on env config
        # For stdio transport (Claude Desktop), auth is configured in
        # the MCP server env block in claude_desktop_config.json.
        # For SSE transport, auth can be passed as a tool argument.
        if MCP_API_KEY and "api_key" in arguments:
            if arguments["api_key"] != MCP_API_KEY:
                return [types.TextContent(
                    type="text",
                    text=json.dumps({"error": "Invalid API key", "success": False}),
                )]
            arguments.pop("api_key")

        try:
            if name == "search_reddit":
                result = await search_reddit(
                    query=arguments.get("query", ""),
                    target_market=arguments.get("target_market", ""),
                )
            elif name == "search_hn":
                result = await search_hn(
                    query=arguments.get("query", ""),
                )
            elif name == "search_research":
                result = await search_research(
                    idea=arguments.get("idea", ""),
                    target_market=arguments.get("target_market", ""),
                    business_model=arguments.get("business_model", ""),
                )
            elif name == "generate_pitch":
                result = await generate_pitch(
                    idea=arguments.get("idea", ""),
                    target_market=arguments.get("target_market", ""),
                    business_model=arguments.get("business_model", ""),
                )
            elif name == "estimate_pricing":
                result = await estimate_pricing(
                    idea=arguments.get("idea", ""),
                    target_market=arguments.get("target_market", ""),
                    business_model=arguments.get("business_model", ""),
                )
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [types.TextContent(type="text", text=result)]

        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": str(e), "success": False}),
            )]

    return server


# ── Entry Points ──────────────────────────────────────

async def run_stdio():
    """Run MCP server over stdio (for Claude Desktop)."""
    server = create_mcp_server()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="pitchforge-mcp",
                server_version="0.1.0",
            ),
        )


def run_sse(host: str = "0.0.0.0", port: int = 8087):
    """Run MCP server over SSE (for Cursor or HTTP clients)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    import uvicorn

    server = create_mcp_server()
    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                InitializationOptions(
                    server_name="pitchforge-mcp",
                    server_version="0.1.0",
                ),
            )

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages", app=sse.handle_post_message),
        ],
    )

    uvicorn.run(app, host=host, port=port)


# ── CLI ────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PitchForge MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (stdio for Claude Desktop, sse for Cursor)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="SSE host")
    parser.add_argument("--port", type=int, default=8087, help="SSE port")

    args = parser.parse_args()

    if args.transport == "sse":
        run_sse(host=args.host, port=args.port)
    else:
        asyncio.run(run_stdio())
