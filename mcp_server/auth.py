"""MCP Server authentication.

Uses MCP_API_KEY env var for Bearer token auth.
If MCP_API_KEY is not set, all requests are allowed (dev mode).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def get_mcp_api_key() -> Optional[str]:
    """Get the MCP API key from environment."""
    return os.getenv("MCP_API_KEY")


def verify_token(token: str) -> bool:
    """Verify a Bearer token against the configured MCP_API_KEY.

    Args:
        token: The Bearer token from the Authorization header.

    Returns:
        True if valid or if no API key is configured (dev mode).
    """
    api_key = get_mcp_api_key()
    if not api_key:
        # Dev mode: no auth required
        return True

    # Constant-time comparison
    if len(token) != len(api_key):
        return False

    result = 0
    for a, b in zip(token, api_key):
        result |= ord(a) ^ ord(b)
    return result == 0
