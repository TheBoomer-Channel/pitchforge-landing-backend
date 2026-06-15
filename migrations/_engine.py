"""
Migration engine for MongoDB/Beanie.

Tracks applied revisions in a `_migrations` collection.
Uses MongoDB atomic findOneAndUpdate for distributed locking.
Designed for zero-downtime: all migrations must be backward-compatible.

Usage:
    from migrations._engine import MigrationEngine
    engine = MigrationEngine(client, db_name)
    await engine.up()           # Apply pending
    await engine.down()         # Rollback last
    await engine.list()         # Show status
    await engine.up(dry_run=True)  # Preview
"""

import hashlib
import importlib
import logging
import os
import pkgutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("migrations")

LOCK_COLLECTION = "_migration_lock"
REVISIONS_COLLECTION = "_migrations"
LOCK_TIMEOUT_SECONDS = int(os.getenv("MIGRATION_LOCK_TIMEOUT", "300"))  # 5 min default
LOCK_DOC_ID = "singleton_lock"


class MigrationEngine:
    """Orchestrates MongoDB schema and data migrations."""

    def __init__(self, db, db_name: str):
        self.db = db
        self.db_name = db_name
        self._lock_col = db[LOCK_COLLECTION]
        self._rev_col = db[REVISIONS_COLLECTION]

    # ── Locking ──────────────────────────────────────────

    async def acquire_lock(self) -> bool:
        """Try to acquire a distributed lock. Returns True if acquired."""
        now = datetime.now(timezone.utc)
        lock_id = f"{self.db_name}-{now.timestamp()}-{id(self)}"

        # Try to insert lock doc (fails if exists)
        try:
            result = await self._lock_col.find_one_and_update(
                {
                    "_id": LOCK_DOC_ID,
                    "$or": [
                        {"expires_at": {"$lt": now}},
                        {"expires_at": {"$exists": False}},
                    ],
                },
                {
                    "$set": {
                        "lock_id": lock_id,
                        "acquired_at": now,
                        "expires_at": now.replace(second=now.second + 30),
                    }
                },
                upsert=True,
            )
            # If result is None, the insert/update might have conflicted
            if result is None:
                # Check if we just created it (upsert with no match)
                doc = await self._lock_col.find_one({"_id": LOCK_DOC_ID})
                if doc and doc.get("lock_id") == lock_id:
                    return True
            return result is not None
        except Exception:
            return False

    async def release_lock(self):
        """Release the lock."""
        try:
            await self._lock_col.delete_one({"_id": LOCK_DOC_ID})
        except Exception:
            pass

    async def _refresh_lock(self):
        """Refresh lock TTL while a long migration runs."""
        try:
            now = datetime.now(timezone.utc)
            await self._lock_col.update_one(
                {"_id": LOCK_DOC_ID},
                {"$set": {"expires_at": now.replace(second=now.second + 30)}},
            )
        except Exception:
            pass

    # ── Revision discovery ───────────────────────────────

    def _discover_revisions(self) -> list[dict]:
        """Discover all migration modules in migrations.versions."""
        revisions = []
        versions_pkg = "migrations.versions"

        try:
            import migrations.versions as pkg

            for importer, modname, ispkg in pkgutil.iter_modules(
                pkg.__path__, prefix=f"{versions_pkg}."
            ):
                if ispkg or modname == f"{versions_pkg}.__init__":
                    continue
                try:
                    mod = importlib.import_module(modname)
                    rev = getattr(mod, "REVISION", None)
                    if rev:
                        revisions.append(
                            {
                                "module": mod,
                                "revision": rev,
                                "down_revision": getattr(mod, "DOWN_REVISION", None),
                                "description": getattr(mod, "DESCRIPTION", ""),
                                "path": modname.replace(".", "/") + ".py",
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed to load migration {modname}: {e}")
        except Exception as e:
            logger.warning(f"Failed to discover migrations: {e}")

        revisions.sort(key=lambda r: r["revision"])
        return revisions

    def _checksum(self, module) -> str:
        """Compute checksum of a migration module source."""
        try:
            source = Path(module.__file__).read_text()
            return hashlib.sha256(source.encode()).hexdigest()[:16]
        except Exception:
            return ""

    # ── Migration operations ─────────────────────────────

    async def up(self, dry_run: bool = False, target: Optional[str] = None) -> list[str]:
        """Apply pending migrations. Returns list of applied revisions."""
        if not await self.acquire_lock():
            logger.error("Could not acquire lock — another migration may be running")
            raise RuntimeError("Migration lock acquisition failed")

        applied_list = []
        try:
            revisions = self._discover_revisions()
            applied = await self._get_applied()
            applied_ids = {r["revision"] for r in applied}

            for rev in revisions:
                if rev["revision"] in applied_ids:
                    continue
                if target and rev["revision"] > target:
                    break

                logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Applying {rev['revision']}: {rev['description']}")

                if not dry_run:
                    cksum = self._checksum(rev["module"])
                    try:
                        await rev["module"].upgrade(self.db)
                        await self._rev_col.insert_one(
                            {
                                "revision": rev["revision"],
                                "down_revision": rev["down_revision"],
                                "description": rev["description"],
                                "checksum": cksum,
                                "applied_at": datetime.now(timezone.utc),
                            }
                        )
                        logger.info(f"  ✅ {rev['revision']} applied")
                    except Exception as e:
                        logger.error(f"  ❌ {rev['revision']} failed: {e}")
                        raise

                applied_list.append(rev["revision"])

                # Refresh lock every migration
                if not dry_run:
                    await self._refresh_lock()

        finally:
            await self.release_lock()

        return applied_list

    async def down(self, dry_run: bool = False, steps: int = 1) -> list[str]:
        """Rollback the last N migrations. Returns list of rolled-back revisions."""
        if not await self.acquire_lock():
            raise RuntimeError("Migration lock acquisition failed")

        rolled_back = []
        try:
            applied = await self._get_applied()
            if not applied:
                logger.info("No migrations to roll back.")
                return []

            for rev in sorted(applied, key=lambda r: r["applied_at"], reverse=True)[:steps]:
                module = self._find_module(rev["revision"])
                if not module:
                    logger.warning(f"Cannot find module for {rev['revision']} — skipping")
                    continue

                if not hasattr(module, "downgrade"):
                    logger.warning(f"{rev['revision']} has no downgrade — skipping")
                    continue

                logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Rolling back {rev['revision']}: {rev.get('description', '')}")

                if not dry_run:
                    try:
                        await module.downgrade(self.db)
                        await self._rev_col.delete_one({"revision": rev["revision"]})
                        logger.info(f"  ✅ {rev['revision']} rolled back")
                    except Exception as e:
                        logger.error(f"  ❌ {rev['revision']} rollback failed: {e}")
                        raise

                rolled_back.append(rev["revision"])

                if not dry_run:
                    await self._refresh_lock()

        finally:
            await self.release_lock()

        return rolled_back

    async def list(self) -> list[dict]:
        """List all migrations with their status (applied/pending)."""
        revisions = self._discover_revisions()
        applied = await self._get_applied()
        applied_ids = {r["revision"] for r in applied}

        result = []
        for rev in revisions:
            is_applied = rev["revision"] in applied_ids
            app = next((a for a in applied if a["revision"] == rev["revision"]), None)
            result.append(
                {
                    "revision": rev["revision"],
                    "description": rev["description"],
                    "status": "applied" if is_applied else "pending",
                    "applied_at": app.get("applied_at").isoformat() if app and app.get("applied_at") else None,
                    "checksum": app.get("checksum", "") if app else "",
                }
            )
        return result

    async def status(self) -> dict:
        """Return a summary of migration state."""
        revisions = self._discover_revisions()
        applied = await self._get_applied()
        return {
            "total": len(revisions),
            "applied": len(applied),
            "pending": len(revisions) - len(applied),
            "latest_applied": applied[-1]["revision"] if applied else None,
            "latest_available": revisions[-1]["revision"] if revisions else None,
        }

    # ── helpers ──────────────────────────────────────────

    async def _get_applied(self) -> list[dict]:
        """Get all applied revisions sorted by applied_at."""
        cursor = self._rev_col.find().sort("applied_at", 1)
        return await cursor.to_list(length=None)

    def _find_module(self, revision: str):
        """Find the module for a given revision ID."""
        for rev in self._discover_revisions():
            if rev["revision"] == revision:
                return rev["module"]
        return None
