"""Authentication — Clerk JWT verification and tier-based authorization.

Uses Clerk's JWKS endpoint for standard RS256 JWT verification.
No longer depends on clerk-backend-api SDK (v5.x removed jwks_helpers).
"""

import logging
import time
from typing import Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .database import User

logger = logging.getLogger(__name__)

# ── Tier hierarchy ─────────────────────────────────────

TIER_ORDER = {
    "free": 0,
    "starter": 1,
    "pro": 2,
    "code_mvp": 3,
}

# ── JWKS cache ─────────────────────────────────────────

_jwks_cache: dict = {"keys": [], "expires_at": 0}
_JWKS_CACHE_TTL = 3600  # 1 hour


async def _fetch_jwks() -> dict:
    """Fetch Clerk's JWKS from the well-known endpoint.

    Caches in memory for _JWKS_CACHE_TTL seconds.
    The Clerk domain is hardcoded to the user's Clerk instance.
    """
    global _jwks_cache

    now = time.time()
    if _jwks_cache["keys"] and _jwks_cache["expires_at"] > now:
        return _jwks_cache

    # The Clerk instance domain — hardcoded to the user's configured instance
    # Configurable via CLERK_AUTHORIZED_PARTIES or the publishable key
    clerk_domain = "blessed-octopus-60.clerk.accounts.dev"

    jwks_url = f"https://{clerk_domain}/.well-known/jwks.json"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            _jwks_cache = {
                "keys": resp.json().get("keys", []),
                "expires_at": now + _JWKS_CACHE_TTL,
            }
            logger.info(f"JWKS fetched from {jwks_url} ({len(_jwks_cache['keys'])} keys)")
    except Exception as e:
        logger.warning(f"JWKS fetch failed ({jwks_url}): {e}")
        # Return stale cache if available
        if _jwks_cache["keys"]:
            return _jwks_cache
        raise

    return _jwks_cache


async def _get_public_key(token: str) -> Optional[dict]:
    """Get the JWK matching the token's Key ID (kid)."""
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception:
        return None

    kid = unverified_header.get("kid")
    if not kid:
        return None

    jwks = await _fetch_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


# ── OAuth2 scheme ──────────────────────────────────────

oauth2_scheme = HTTPBearer(auto_error=False)


# ── Tier dependency ────────────────────────────────────

def require_tier(min_tier: str):
    """Dependency factory: require user to have at least `min_tier`."""
    async def _check(
        user=Depends(get_current_user),
    ):
        user_level = TIER_ORDER.get(user.tier, 0)
        required_level = TIER_ORDER.get(min_tier, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"This feature requires at least the {min_tier} tier. "
                f"Your tier: {user.tier}.",
            )
        return user

    return _check


# ── Clerk JWT verification ─────────────────────────────

async def verify_clerk_token(token: str) -> Optional[str]:
    """Verify a Clerk session JWT and return the user ID (sub claim).

    Uses Clerk's JWKS endpoint for RS256 signature verification.
    """
    if not settings.CLERK_SECRET_KEY:
        # Dev mode: accept any Bearer token as a user ID
        return token

    try:
        # Get the public key matching the JWT's kid
        public_key_jwk = await _get_public_key(token)
        if not public_key_jwk:
            logger.warning("No matching JWK found for token")
            return None

        # Build the public key from JWK
        rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(public_key_jwk)

        # Derive issuer from the Clerk domain
        issuer = f"https://blessed-octopus-60.clerk.accounts.dev"

        # Decode and verify
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "verify_exp": True,
                "verify_iat": True,
                "require": ["exp", "sub", "iss"],
            },
        )

        user_id = payload.get("sub")
        logger.debug(f"Clerk token verified: user={user_id}")
        return user_id

    except jwt.ExpiredSignatureError:
        logger.warning("Clerk token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Clerk token invalid: {e}")
        return None
    except Exception as e:
        logger.warning(f"Clerk token verification error: {e}")
        return None


# ── Get or create user ─────────────────────────────────

async def get_or_create_user(clerk_user_id: str, email: str = "", name: str = "") -> User:
    """Find a user by Clerk ID, or create one if not found.

    This is called on first login to sync Clerk auth with our DB.
    """
    user = await User.find_one(User.clerk_user_id == clerk_user_id)
    if user:
        # Update email/name if changed in Clerk
        if email and email != user.email:
            user.email = email
        if name and name != user.name:
            user.name = name
        await user.save()
        return user

    # Create new user
    user = User(
        clerk_user_id=clerk_user_id,
        email=email or "",
        name=name or "",
        tier="free",
    )
    await user.insert()
    logger.info(f"New user created: {clerk_user_id} ({email})")
    return user


# ── User dependencies ──────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
) -> User:
    """Extract authenticated user from Clerk session JWT.

    Verifies the Bearer token against Clerk's JWKS, then returns
    the user from MongoDB (creating if first login).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Verify Clerk session token
    clerk_user_id = await verify_clerk_token(credentials.credentials)
    if not clerk_user_id:
        # Fallback for dev: try to decode as direct user ID
        if not settings.CLERK_SECRET_KEY:
            clerk_user_id = credentials.credentials
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token. "
                "Get a new token from Clerk's SignIn flow or use an API key.",
            )

    # Get or create user in our DB
    user = await get_or_create_user(clerk_user_id)

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
) -> Optional[User]:
    """Return user if authenticated, otherwise None (no error)."""
    if credentials is None:
        return None

    clerk_user_id = await verify_clerk_token(credentials.credentials)
    if not clerk_user_id:
        if not settings.CLERK_SECRET_KEY:
            clerk_user_id = credentials.credentials
        else:
            return None

    return await get_or_create_user(clerk_user_id)
