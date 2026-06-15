"""Legal routes — TASK-012.

Public endpoints to read legal documents, plus an authenticated
endpoint to record a user's acceptance.

  * GET  /api/v1/legal/version       — list of (slug → current_version)
  * GET  /api/v1/legal/{slug}        — current version of a doc (markdown)
  * GET  /api/v1/legal/{slug}/history — version history (titles + dates)
  * POST /api/v1/legal/accept        — record acceptance (authenticated)
  * GET  /api/v1/legal/pending       — docs the user has not yet accepted
                                        (authenticated; 0 = OK to proceed)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from ..auth import get_current_user
from ..config import settings
from ..database import User
from ..models.legal import LegalDocument, UserLegalAcceptance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/legal", tags=["legal"])

# ── Constants ──────────────────────────────────────────

CURRENT_VERSION = "1.0.0"

# Resolve the on-disk location of the legal markdown files.
# `app/routes/legal.py` → `app/` → `code/backend/` → `content/legal/`
_LEGAL_DIR = (
    Path(__file__).resolve().parent.parent.parent / "content" / "legal"
)

# Slug → file basename (without .md)
SLUG_TO_BASENAME = {
    "terms": "terms-of-service",
    "privacy": "privacy-policy",
    "cookies": "cookie-policy",
    "aup": "acceptable-use",
}

VALID_SLUGS = set(SLUG_TO_BASENAME.keys())

# In-memory index of titles (loaded from disk on first access)
_TITLES_CACHE: dict[str, dict[str, str]] = {}


# ── Helpers ────────────────────────────────────────────


def _content_path(slug: str, version: str = CURRENT_VERSION) -> Path:
    """Resolve the on-disk path of a legal document."""
    if slug not in SLUG_TO_BASENAME:
        raise KeyError(slug)
    return _LEGAL_DIR / version / f"{SLUG_TO_BASENAME[slug]}.md"


def _read_markdown(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding="utf-8")


def _extract_title(markdown: str, fallback: str) -> str:
    """Pull the first H1 from a markdown file as a human title."""
    m = re.search(r"^#\s+(.+?)$", markdown, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return fallback


def _extract_effective_date(markdown: str) -> Optional[str]:
    """Look for 'Effective date: YYYY-MM-DD' in the first 5 lines."""
    head = "\n".join(markdown.splitlines()[:8])
    m = re.search(r"Effective date:\s*(\d{4}-\d{2}-\d{2})", head)
    return m.group(1) if m else None


def _seed_legal_documents() -> None:
    """Scan disk and upsert LegalDocument rows so the DB stays in sync with
    the filesystem. Idempotent — safe to call on every startup.
    """
    import asyncio

    async def _run() -> None:
        for slug, basename in SLUG_TO_BASENAME.items():
            path = _content_path(slug, CURRENT_VERSION)
            try:
                md = _read_markdown(path)
            except FileNotFoundError:
                logger.warning(f"Legal doc missing on disk: {path}")
                continue

            title = _extract_title(md, basename)
            eff_str = _extract_effective_date(md)
            effective_at = (
                datetime.fromisoformat(eff_str).replace(tzinfo=timezone.utc)
                if eff_str
                else datetime.now(timezone.utc)
            )

            existing = await LegalDocument.find_one(
                LegalDocument.slug == slug,
                LegalDocument.version == CURRENT_VERSION,
            )
            if existing:
                # Update title/effective_at if changed
                if existing.title != title or existing.effective_at != effective_at:
                    existing.title = title
                    existing.effective_at = effective_at
                    await existing.save()
            else:
                # Mark older versions as superseded
                older = await LegalDocument.find(
                    LegalDocument.slug == slug,
                    LegalDocument.superseded_at == None,
                ).to_list()
                for old in older:
                    old.superseded_at = effective_at
                    await old.save()

                await LegalDocument(
                    slug=slug,
                    version=CURRENT_VERSION,
                    title=title,
                    effective_at=effective_at,
                    requires_acceptance=True,
                ).insert()
                logger.info(f"Legal doc registered: {slug} v{CURRENT_VERSION}")

    # Schedule the seed in the background; never block startup
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_run())
    except RuntimeError:
        # No loop yet (called too early in startup); skip — will be seeded on first request
        pass


# Run seed at import time (FastAPI app lifespan will retry via first request)
_seed_legal_documents()


# ── Public endpoints ───────────────────────────────────


@router.get("/version", summary="List current legal document versions")
async def list_current_versions() -> dict:
    """Returns `{slug: current_version}` for all published legal docs.

    The frontend uses this to decide whether to show a "we've updated
    our terms" banner. Cheap, public, no auth.
    """
    docs = await LegalDocument.find(
        LegalDocument.superseded_at == None,
    ).to_list()
    return {d.slug: d.version for d in docs}


@router.get("/pending", summary="List legal docs the current user has not accepted")
async def list_pending(
    user: User = Depends(get_current_user),
) -> dict:
    """Returns `{slug: current_version}` for docs the user has NOT accepted
    at the current version. Empty dict means the user is fully compliant.
    """
    current = await LegalDocument.find(
        LegalDocument.superseded_at == None,
    ).to_list()
    pending: dict[str, str] = {}
    for d in current:
        if not d.requires_acceptance:
            continue
        accepted = await UserLegalAcceptance.find_one(
            UserLegalAcceptance.user_id == user.clerk_user_id,
            UserLegalAcceptance.doc_slug == d.slug,
            UserLegalAcceptance.version == d.version,
        )
        if not accepted:
            pending[d.slug] = d.version
    return pending


@router.get("/{slug}/history", summary="Version history for a legal document")
async def get_history(slug: str) -> list[dict]:
    if slug not in VALID_SLUGS:
        raise HTTPException(status_code=404, detail=f"Unknown legal doc: {slug}")
    docs = await LegalDocument.find(
        LegalDocument.slug == slug,
    ).sort("-effective_at").to_list()
    return [
        {
            "version": d.version,
            "title": d.title,
            "effective_at": d.effective_at.isoformat(),
            "superseded_at": d.superseded_at.isoformat() if d.superseded_at else None,
            "is_current": d.superseded_at is None,
        }
        for d in docs
    ]


@router.get("/{slug}", summary="Read the current version of a legal document")
async def get_document(slug: str, version: Optional[str] = None) -> dict:
    if slug not in VALID_SLUGS:
        raise HTTPException(status_code=404, detail=f"Unknown legal doc: {slug}")

    version = version or CURRENT_VERSION
    path = _content_path(slug, version)
    try:
        markdown = _read_markdown(path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version} of {slug} not found",
        )

    title = _extract_title(markdown, SLUG_TO_BASENAME[slug])
    eff_str = _extract_effective_date(markdown)
    effective_at = (
        datetime.fromisoformat(eff_str).replace(tzinfo=timezone.utc)
        if eff_str
        else datetime.now(timezone.utc)
    )

    # Word count + reading time (helpful for the UI badge)
    word_count = len(markdown.split())
    reading_minutes = max(1, round(word_count / 200))

    return {
        "slug": slug,
        "version": version,
        "title": title,
        "effective_at": effective_at.isoformat(),
        "word_count": word_count,
        "reading_minutes": reading_minutes,
        "content_md": markdown,
    }


# ── Authenticated endpoints ────────────────────────────


@router.post("/accept", summary="Record acceptance of legal documents")
async def accept_legal(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Record acceptance of one or more legal documents at a specific version.

    Idempotent — accepting the same (doc, version) twice is a no-op
    (we still log a new row for audit purposes).
    """
    body = await request.json()
    acceptances = body.get("acceptances", [])

    if not isinstance(acceptances, list) or not acceptances:
        raise HTTPException(
            status_code=400,
            detail="`acceptances` must be a non-empty list of {slug, version}",
        )

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    for entry in acceptances:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        version = entry.get("version")
        if slug not in VALID_SLUGS or not version:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid acceptance: {entry}",
            )

        # Verify the version exists
        doc = await LegalDocument.find_one(
            LegalDocument.slug == slug, LegalDocument.version == version
        )
        if not doc:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown version: {slug} v{version}",
            )

        await UserLegalAcceptance(
            user_id=user.clerk_user_id,
            doc_slug=slug,
            version=version,
            ip=ip,
            user_agent=ua,
            source=entry.get("source", "settings"),
        ).insert()

    logger.info(
        f"Legal acceptances recorded: user={user.clerk_user_id} "
        f"count={len(acceptances)}",
    )
    return Response(status_code=204)
