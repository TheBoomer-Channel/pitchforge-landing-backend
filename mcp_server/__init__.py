"""MCP Server — Model Context Protocol for PitchForge.

Exposes PitchForge capabilities as MCP tools so that AI agents
(Claude, Cursor, Codebuff, etc.) can research ideas, generate
pitch decks, landing pages, and pricing directly via the protocol.

Transport: SSE (Server-Sent Events) on port 8087.
Auth: Bearer token via MCP_API_KEY env var.
"""

__version__ = "0.1.0"
