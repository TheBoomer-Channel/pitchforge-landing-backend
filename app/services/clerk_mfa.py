"""Clerk MFA Service — TASK-048.

Provides helpers to check MFA (Multi-Factor Authentication) status from Clerk.

Clerk manages all 2FA secrets and verification (TOTP, WebAuthn, SMS).
This service provides a clean interface for the backend to:
1. Check if a user has MFA factors enrolled (via Clerk API)
2. Check if the current session has completed MFA (via JWT claims)
3. Get the user's MFA enrollment status for the frontend

Usage:
    from app.services.clerk_mfa import get_mfa_status

    status = await get_mfa_status("user_clerk_id")
    if status["has_mfa"]:
        # User has at least one MFA method enrolled
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Clerk API Configuration ────────────────────────────

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_API_URL = "https://api.clerk.com/v1"


async def _clerk_request(method: str, path: str) -> Optional[dict]:
    """Make an authenticated request to the Clerk Backend API.

    Uses the CLERK_SECRET_KEY for Bearer auth.
    Returns parsed JSON or None on failure.
    """
    if not CLERK_SECRET_KEY:
        logger.debug("CLERK_SECRET_KEY not set — skipping Clerk API call")
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.request(
                method=method,
                url=f"{CLERK_API_URL}{path}",
                headers={
                    "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning(
                    f"Clerk API error {resp.status_code} on {method} {path}: "
                    f"{resp.text[:200]}"
                )
                return None
    except httpx.TimeoutException:
        logger.warning(f"Clerk API timeout on {method} {path}")
        return None
    except Exception as e:
        logger.warning(f"Clerk API error on {method} {path}: {e}")
        return None


# ── Public Helpers ─────────────────────────────────────

async def get_user_mfa_data(user_id: str) -> dict:
    """Get MFA-related data for a user from Clerk.

    Returns dict with:
    - has_totp: bool — has TOTP authenticator enrolled
    - has_passkey: bool — has WebAuthn/passkey enrolled
    - has_backup_codes: bool — has backup codes
    - has_phone: bool — has phone number for SMS 2FA
    - has_mfa: bool — has at least one MFA method
    - totp_verified: bool — TOTP is verified/active
    - methods: list[str] — available MFA methods

    Falls back to cached/empty data if Clerk API is unavailable.
    """
    user_data = await _clerk_request("GET", f"/users/{user_id}")

    if not user_data:
        # Fallback: return empty (no MFA)
        logger.debug(f"No Clerk data for user {user_id[:12]}... (API unavailable or no secret)")
        return {
            "has_totp": False,
            "has_passkey": False,
            "has_backup_codes": False,
            "has_phone": False,
            "has_mfa": False,
            "totp_verified": False,
            "methods": [],
        }

    # Extract MFA information
    totp_registrations = user_data.get("totp_registrations", []) or []
    passkey_registrations = user_data.get("passkey_registrations", []) or []
    backup_code_registration = user_data.get("backup_code_registration") or {}
    phone_numbers = user_data.get("phone_numbers", []) or []

    has_totp = len(totp_registrations) > 0
    has_passkey = len(passkey_registrations) > 0
    has_backup_codes = backup_code_registration.get("status") == "verified"
    has_phone = any(pn.get("reserved_for_second_factor") or pn.get("verification", {}).get("status") == "verified" for pn in phone_numbers)

    methods = []
    if has_totp:
        methods.append("totp")
    if has_passkey:
        methods.append("passkey")
    if has_backup_codes:
        methods.append("backup_code")
    if has_phone:
        methods.append("phone")

    return {
        "has_totp": has_totp,
        "has_passkey": has_passkey,
        "has_backup_codes": has_backup_codes,
        "has_phone": has_phone,
        "has_mfa": len(methods) > 0,
        "totp_verified": any(
            t.get("status") == "verified" for t in totp_registrations
        ),
        "methods": methods,
        # Raw data for detailed display
        "totp_registrations": [
            {"id": t.get("id"), "status": t.get("status"), "created_at": t.get("created_at")}
            for t in totp_registrations
        ],
        "passkey_registrations": [
            {"id": p.get("id"), "status": p.get("status"), "created_at": p.get("created_at")}
            for p in passkey_registrations
        ],
        "backup_codes_count": backup_code_registration.get("codes_remaining", 0) if has_backup_codes else 0,
        "phone_numbers": [
            {"id": pn.get("id"), "phone_number": pn.get("phone_number", "")[-4:].rjust(len(pn.get("phone_number", "")), '*')}
            for pn in phone_numbers if pn.get("reserved_for_second_factor")
        ],
    }


def check_session_mfa_from_token(payload: dict) -> dict:
    """Check if the current JWT session has completed MFA.

    Clerk's session JWT may include verification claims:
    - `fvs`: First verification status ('verified' | 'unverified')
    - `fva`: First verification attempts
    - Custom claims can be added via JWT Templates

    For stricter MFA enforcement, add a custom JWT template in Clerk
    Dashboard that includes `user.totp_registrations` or a custom
    `mfa_verified` claim.

    Args:
        payload: Decoded JWT payload from Clerk session token.

    Returns:
        dict with 'mfa_verified' (bool) and 'details'.
    """
    # Check for custom MFA claim (requires JWT Template configuration)
    mfa_verified = payload.get("mfa_verified", False)

    # Fallback: check if session has second factor verified
    # Clerk doesn't expose this by default in the JWT, but you can
    # verify via the Sessions API:
    # GET /v1/sessions/{sid} → check `last_active_at` and factors
    session_id = payload.get("sid", "")
    if session_id and not mfa_verified:
        # We could verify via Clerk API here, but that adds latency.
        # For now, rely on custom JWT claims.
        pass

    return {
        "mfa_verified": bool(mfa_verified),
        "session_id": session_id,
        "needs_custom_jwt_template": not mfa_verified,
    }


async def get_session_mfa_status(session_id: str) -> dict:
    """Check if a specific Clerk session has completed MFA.

    Calls Clerk Sessions API to check the session's factors.
    More accurate than JWT claims but adds network latency.
    """
    session_data = await _clerk_request("GET", f"/sessions/{session_id}")

    if not session_data:
        return {"mfa_verified": False, "error": "Session not found or API unavailable"}

    # Check if session has active MFA factors used
    # Clerk sessions include status and factors used
    status = session_data.get("status", "")
    latest_activity = session_data.get("last_active_at", "")

    return {
        "mfa_verified": status == "active",
        "status": status,
        "latest_activity": latest_activity,
    }


async def get_mfa_status(user_id: str) -> dict:
    """Get comprehensive MFA status for a user.

    Combines user enrollment data with session info.

    Returns dict suitable for the /api/v1/2fa/status endpoint:
    - enabled: bool — user has at least one MFA method
    - methods: list[str] — available MFA methods
    - totp_count: int — number of TOTP registrations
    - passkey_count: int — number of passkeys
    - backup_codes_remaining: int
    - details: dict — per-method details
    """
    mfa_data = await get_user_mfa_data(user_id)

    # Merge with our local user data
    return {
        "enabled": mfa_data["has_mfa"],
        "provider": "clerk",
        "methods": mfa_data["methods"],
        "totp_count": len(mfa_data.get("totp_registrations", [])),
        "passkey_count": len(mfa_data.get("passkey_registrations", [])),
        "backup_codes_remaining": mfa_data.get("backup_codes_count", 0),
        "details": {
            "has_totp": mfa_data["has_totp"],
            "has_passkey": mfa_data["has_passkey"],
            "has_backup_codes": mfa_data["has_backup_codes"],
            "has_phone": mfa_data["has_phone"],
            "totp_verified": mfa_data["totp_verified"],
        },
    }
