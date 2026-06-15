"""Settings API routes — API key management with MongoDB/Beanie."""

import logging
import secrets
import uuid
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..database import User, ApiKey

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

KEY_PREFIX = "sf_"


def _generate_key() -> tuple[str, str, str]:
    raw = secrets.token_hex(24)
    full_key = f"{KEY_PREFIX}{raw}"
    prefix = full_key[:12]
    key_hash = bcrypt.hashpw(full_key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return full_key, prefix, key_hash


def verify_api_key(key: str, key_hash: str) -> bool:
    return bcrypt.checkpw(key.encode("utf-8"), key_hash.encode("utf-8"))


@router.get("/api-keys")
async def list_api_keys(user: User = Depends(get_current_user)):
    keys = await ApiKey.find(ApiKey.user_id == user.clerk_user_id, ApiKey.is_active == True).sort(-ApiKey.created_at).to_list()
    return {"keys": [{"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "created_at": k.created_at.isoformat() if k.created_at else None, "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None} for k in keys], "total": len(keys)}


@router.post("/api-keys")
async def create_api_key(name: str = "Default", user: User = Depends(get_current_user)):
    full_key, prefix, key_hash = _generate_key()
    key_id = str(uuid.uuid4())
    api_key = ApiKey(id=key_id, user_id=user.clerk_user_id, name=name, key_prefix=prefix, key_hash=key_hash)
    await api_key.insert()
    return {"id": key_id, "name": name, "key": full_key, "key_prefix": prefix, "message": "Copy this key now — it will not be shown again."}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str, user: User = Depends(get_current_user)):
    key = await ApiKey.find_one(ApiKey.id == key_id, ApiKey.user_id == user.clerk_user_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = False
    await key.save()
    return {"status": "revoked", "id": key_id}
