"""MCP Server — PitchForge tools exposed via Model Context Protocol.

Entry point: python -m mcp_server.server --transport sse --port 8087

The server registers tools that wrap PitchForge's core capabilities:
research, planning, generation, project management, and competitive analysis.
"""

from __future__ import annotations

import logging
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server

from . import auth, tools

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Server identity ────────────────────────────────────

server = Server("pitchforge-mcp")
server.name = "pitchforge-mcp"
server.version = "0.1.0"


# ── Tool implementations ───────────────────────────────

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available PitchForge MCP tools."""
    return [
        types.Tool(
            name="research_idea",
            description="Run full market research on a startup idea across 8 sources (web, HN, Reddit, GitHub, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "The startup idea to research (e.g., 'AI-powered email assistant for Gmail')",
                    },
                    "target_market": {
                        "type": "string",
                        "description": "Optional target market (e.g., 'SaaS', 'healthcare', 'fintech')",
                    },
                    "business_model": {
                        "type": "string",
                        "description": "Optional business model (e.g., 'subscription', 'marketplace')",
                    },
                },
                "required": ["idea"],
            },
        ),
        types.Tool(
            name="generate_assets",
            description="Generate pitch deck, landing page, and pricing page HTML from a research report",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "The startup idea",
                    },
                    "types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["pitch", "landing", "pricing"]},
                        "description": "Asset types to generate. Default: all three.",
                    },
                },
                "required": ["idea"],
            },
        ),
        types.Tool(
            name="analyze_competitors",
            description="Extract structured competitor analysis with table stakes,"
            " differentiation gaps, and pricing landscape",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "The startup idea to analyze competitors for",
                    },
                },
                "required": ["idea"],
            },
        ),
        types.Tool(
            name="check_project_status",
            description="Check the status of an existing PitchForge project",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID to check",
                    },
                },
                "required": ["project_id"],
            },
        ),
        types.Tool(
            name="health_check",
            description="Check if the PitchForge MCP server and API are healthy",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict[str, Any] | None,
) -> list[types.TextContent]:
    """Execute a PitchForge tool and return results."""
    if not arguments:
        arguments = {}

    try:
        if name == "research_idea":
            result = await tools.research_idea(
                idea=arguments.get("idea", ""),
                target_market=arguments.get("target_market"),
                business_model=arguments.get("business_model"),
            )
        elif name == "generate_assets":
            result = await tools.generate_assets(
                idea=arguments.get("idea", ""),
                types=arguments.get("types"),
            )
        elif name == "analyze_competitors":
            result = await tools.analyze_competitors(
                idea=arguments.get("idea", ""),
            )
        elif name == "check_project_status":
            result = await tools.check_project_status(
                project_id=arguments.get("project_id", ""),
            )
        elif name == "health_check":
            result = await tools.health_check()
        else:
            raise ValueError(f"Unknown tool: {name}")

        return [types.TextContent(type="text", text=result)]

    except Exception as e:
        logger.error(f"Tool '{name}' failed: {e}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=f"Error executing '{name}': {e}",
        )]


# ── Auth middleware ────────────────────────────────────

@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """No prompts defined — this is a tool-only MCP server."""
    return []


# ── Main ───────────────────────────────────────────────

def main():
    """Run the MCP server with SSE transport."""
    import argparse

    parser = argparse.ArgumentParser(description="PitchForge MCP Server")
    parser.add_argument("--transport", choices=["sse", "stdio"], default="sse")
    parser.add_argument("--port", type=int, default=8087)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    # Validate API key is configured
    api_key = auth.get_mcp_api_key()
    if not api_key:
        logger.warning(
            "MCP_API_KEY not set — all requests will be allowed without auth. "
            "Set MCP_API_KEY in .env for production."
        )

    if args.transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/mcp/messages")

        # ── Auth middleware for SSE transport ──────────
        class _MCPAuthMiddleware(BaseHTTPMiddleware):
            """Validates Bearer token on all requests except /health."""
            async def dispatch(self, request, call_next):
                if request.url.path == "/health":
                    return await call_next(request)
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
                    if auth.verify_token(token):
                        return await call_next(request)
                if not auth.get_mcp_api_key():
                    return await call_next(request)
                return JSONResponse(
                    status_code=401,
                    content={"error": "Unauthorized",
                             "message": "Valid MCP_API_KEY required"},
                )

        async def handle_sse(request):
            # Use the official MCP SDK pattern for SSE transport
            async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,
            ) as streams:
                await server.run(
                    streams[0],
                    streams[1],
                    server.create_initialization_options(),
                )

        starlette_app = Starlette(
            debug=False,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/mcp/messages", app=sse.handle_post_message),
                Route("/health", endpoint=lambda r: {"status": "ok"}),
            ],
        )
        starlette_app.add_middleware(_MCPAuthMiddleware)

        import uvicorn
        logger.info(f"PitchForge MCP Server starting on {args.host}:{args.port} (SSE)")
        uvicorn.run(starlette_app, host=args.host, port=args.port)
    else:
        # stdio transport (for local CLI agents)
        async def run_stdio():
            async with mcp.server.stdio.stdio_server() as streams:
                await server.run(
                    streams[0],
                    streams[1],
                    server.create_initialization_options(),
                )

        import asyncio
        logger.info("PitchForge MCP Server starting (stdio)")
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
