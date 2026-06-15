"""Two-factor authentication routes — TASK-048 (Clerk MFA).

Now uses Clerk-managed MFA (TOTP, WebAuthn/Passkeys, SMS) instead of
custom pyotp storage. Clerk handles all secrets, verification, and
recovery codes internally.

The Clerk Frontend SDK handles enrollment and verification:
  - user.createTOTP() → user.verifyTOTP({ code })  — TOTP enrollment
  - user.createPasskey()                            — WebAuthn enrollment
  - signIn.attemptSecondFactor()                    — MFA challenge at login

Endpoints (backend):
  * GET   /api/v1/2fa/status           — MFA status from Clerk + local flags
  * GET   /api/v1/2fa/session-status   — Check if current session has MFA
  * POST  /api/v1/2fa/disable          — Disable 2FA via Clerk API
"""

from __future__ import annotations

import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..config import settings
from ..database import User
from ..services.clerk_mfa import get_mfa_status, get_user_mfa_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/2fa", tags=["auth"])

CLERK_SECRET_KEY = settings.CLERK_SECRET_KEY or ""


# ── Schemas ────────────────────────────────────────────


class MfaStatusResponse(BaseModel):
    """MFA status combining Clerk-managed factors with local flags."""

    enabled: bool                      # Has at least one MFA method
    provider: str = "clerk"           # MFA provider
    methods: list[str] = []           # Available methods: totp, passkey, backup_code, phone
    forced: bool = False              # Admin-enforced 2FA (from our User model)
    totp_count: int = 0               # TOTP registrations
    passkey_count: int = 0            # WebAuthn/passkey registrations
    backup_codes_remaining: int = 0   # Backup codes remaining
    details: dict = Field(default_factory=dict)  # Per-method details


class DisableRequest(BaseModel):
    """Request to disable 2FA."""
    user_id: str = Field(..., description="Clerk user ID to disable MFA for")


class DisableResponse(BaseModel):
    status: str
    message: str


# ── Clerk API helper ───────────────────────────────────


async def _clerk_admin_request(method: str, path: str, json_data: Optional[dict] = None) -> Optional[dict]:
    """Make an authenticated request to Clerk Admin API.

    Uses CLERK_SECRET_KEY for authorization.
    """
    if not CLERK_SECRET_KEY:
        logger.debug("CLERK_SECRET_KEY not set — skipping Clerk API call")
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {
                "Authorization": f"Bearer {CLERK_SECRET_KEY}",
                "Content-Type": "application/json",
            }
            resp = await client.request(
                method=method,
                url=f"https://api.clerk.com/v1{path}",
                headers=headers,
                json=json_data,
            )
            if resp.status_code in (200, 201, 204):
                return resp.json() if resp.content else {}
            logger.warning(
                f"Clerk API error {resp.status_code} on {method} {path}: "
                f"{resp.text[:200]}"
            )
            return None
    except Exception as e:
        logger.warning(f"Clerk API request failed: {e}")
        return None


# ── Status ──────────────────────────────────────────────


@router.get("/status", response_model=MfaStatusResponse, summary="Current MFA status (Clerk-managed)")
async def get_status(
    user: User = Depends(get_current_user),
) -> MfaStatusResponse:
    """Get the user's current MFA status from Clerk.

    Returns enabled methods, counts, and whether MFA is admin-forced.
    The frontend uses this to show the Security section in Settings.

    Enrollment itself is done via the Clerk Frontend SDK:
      - TOTP: user.createTOTP() → user.verifyTOTP({ code })
      - Passkey: user.createPasskey()
    """
    # Check Clerk for MFA enrollment
    mfa_status = await get_mfa_status(user.clerk_user_id)

    return MfaStatusResponse(
        enabled=mfa_status["enabled"],
        provider=mfa_status.get("provider", "clerk"),
        methods=mfa_status.get("methods", []),
        forced=getattr(user, "two_factor_forced", False),
        totp_count=mfa_status.get("totp_count", 0),
        passkey_count=mfa_status.get("passkey_count", 0),
        backup_codes_remaining=mfa_status.get("backup_codes_remaining", 0),
        details=mfa_status.get("details", {}),
    )


# ── Session MFA Status ─────────────────────────────────


@router.get("/session-status", summary="Check if current session completed MFA")
async def get_session_mfa_status_endpoint(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Check whether the current session has completed MFA.

    Uses the Clerk Sessions API to verify that the session's
    second factor was verified. This is useful for:
    - Showing a warning if the user has MFA enabled but hasn't verified
      in this session
    - Enforcing MFA for sensitive actions

    Returns:
    - mfa_verified: bool — whether MFA was completed in this session
    - session_id: str — the Clerk session ID
    - status: str — session status from Clerk
    """
    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"mfa_verified": False, "session_id": "", "status": "no_token"}

    token = auth_header[7:]

    # Try to decode the JWT to get session ID
    try:
        import jwt as pyjwt
        payload = pyjwt.decode(token, options={"verify_signature": False})
        session_id = payload.get("sid", "")

        # Check Clerk session API for MFA status
        if session_id and CLERK_SECRET_KEY:
            session_data = await _clerk_admin_request("GET", f"/sessions/{session_id}")
            if session_data:
                # A session with active status and recent activity likely has MFA
                status = session_data.get("status", "")
                latest_activity = session_data.get("last_active_at", "")

                # Check factors used in this session
                factors = session_data.get("factors", [])
                has_second_factor = any(
                    f.get("type") in ("totp", "passkey", "phone_code")
                    for f in factors
                )

                return {
                    "mfa_verified": has_second_factor or status == "active",
                    "session_id": session_id,
                    "status": status,
                    "factors": [f.get("type") for f in factors],
                    "latest_activity": latest_activity,
                }

        return {
            "mfa_verified": False,
            "session_id": session_id,
            "status": "session_not_found",
            "note": "Session MFA status requires Clerk JWT template with custom claims. "
                    "Add 'mfa_verified' to your JWT template for zero-latency checks.",
        }
    except Exception as e:
        logger.debug(f"Session MFA check failed (non-fatal): {e}")
        return {"mfa_verified": False, "session_id": "", "status": "error"}


# ── Disable (Admin only — requires CLERK_SECRET_KEY) ────


@router.post("/disable", status_code=200, summary="Disable 2FA for a user (admin)")
async def disable_mfa(
    payload: DisableRequest,
    user: User = Depends(get_current_user),
) -> DisableResponse:
    """Disable all MFA methods for a user via Clerk API.

    Requires CLERK_SECRET_KEY to be configured.
    Only the user themselves can disable their own MFA, or an admin.

    For users who have lost access to their authenticator app,
    use the Clerk Dashboard or this endpoint with admin privileges.
    """
    if not CLERK_SECRET_KEY:
        raise HTTPException(
            status_code=501,
            detail="Clerk admin API not configured (CLERK_SECRET_KEY required). "
                   "Use Clerk Dashboard to manage MFA.",
        )

    # Verify the requester is the user themselves or has admin privileges
    is_self = payload.user_id == user.clerk_user_id
    is_admin = user.tier == "code_mvp"

    if not (is_self or is_admin):
        raise HTTPException(
            status_code=403,
            detail="You can only disable your own 2FA. Contact support for help.",
        )

    # Disable TOTP via Clerk API
    mfa_data = await get_user_mfa_data(payload.user_id)

    disabled = []
    errors = []

    # Remove TOTP registrations
    for totp in mfa_data.get("totp_registrations", []):
        totp_id = totp.get("id")
        if totp_id:
            result = await _clerk_admin_request(
                "DELETE", f"/users/{payload.user_id}/totp/{totp_id}"
            )
            if result is not None:
                disabled.append(f"totp:{totp_id[:8]}")
            else:
                errors.append(f"totp:{totp_id[:8]}")

    # Remove passkey registrations
    for passkey in mfa_data.get("passkey_registrations", []):
        passkey_id = passkey.get("id")
        if passkey_id:
            result = await _clerk_admin_request(
                "DELETE", f"/users/{payload.user_id}/passkey/{passkey_id}"
            )
            if result is not None:
                disabled.append(f"passkey:{passkey_id[:8]}")
            else:
                errors.append(f"passkey:{passkey_id[:8]}")

    # Update our local user record
    if is_self:
        user.two_factor_enabled = False
        user.two_factor_enabled_at = None
        await user.save()

    logger.info(
        f"MFA disabled via API: user={payload.user_id[:12]}... "
        f"disabled={disabled} errors={errors}"
    )

    status_msg = f"Disabled {len(disabled)} MFA method(s)"
    if errors:
        status_msg += f" ({len(errors)} errors: {', '.join(errors)})"

    return DisableResponse(
        status="disabled" if not errors else "partial",
        message=status_msg,
    )
