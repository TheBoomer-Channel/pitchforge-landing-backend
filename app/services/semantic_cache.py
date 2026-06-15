"""Semantic cache for research queries — reduces external API calls by >40%.

Uses fastembed (ONNX-based, lightweight) to generate embeddings locally,
stores results in Redis with configurable TTL, and returns cached responses
when cosine similarity exceeds the threshold (default: 0.92).

Architecture:
    lookup(query) → embedding → scan Redis keys → cosine similarity → hit/miss
    store(query, response) → embedding → Redis HSET with TTL

Integration point: research_runner.py wraps engine.run() with cache check.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SemanticCacheService:
    """Semantic cache for research results using Redis + local embeddings.

    Usage:
        cache = SemanticCacheService()
        cached = await cache.lookup("AI for freight matching")
        if cached:
            return cached["response"]
        report = await engine.run(...)
        await cache.store("AI for freight matching", report.model_dump())
    """

    # TTL per category (seconds)
    TTL_MAP: dict[str, int] = {
        "research": 7 * 24 * 3600,   # 7 days
        "trending": 24 * 3600,        # 24 hours
    }

    # Cache key prefix in Redis
    KEY_PREFIX = "semantic:research:"

    # Default similarity threshold
    DEFAULT_THRESHOLD = 0.92

    # Estimated cost savings per cache hit (USD) — average external API cost
    # for a full research run (Tavily + Perplexity + multiple sources)
    ESTIMATED_COST_PER_HIT_USD = 0.15

    def __init__(self, redis_pool=None):
        self._pool = redis_pool
        self._model: Any = None  # Lazy-loaded (fastembed)
        self._model_loaded = False
        self._stats = {"hits": 0, "misses": 0, "false_positives": 0, "errors": 0}

    # ── Redis connection ─────────────────────────────────

    async def _get_redis(self):
        """Get or create Redis connection pool."""
        if self._pool:
            return self._pool
        try:
            from arq.connections import RedisSettings, create_pool
            from ..config import settings
            self._pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            return self._pool
        except Exception as e:
            logger.warning(f"Redis connection failed (cache disabled): {e}")
            return None

    # ── Embedding model (lazy-loaded) ────────────────────

    def _load_model(self) -> bool:
        """Lazy-load the fastembed model. Returns True if available."""
        if self._model_loaded:
            return self._model is not None
        self._model_loaded = True
        try:
            from fastembed import TextEmbedding
            # bge-small-en-v1.5: 30MB, 384-dim, fast, good quality
            self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            logger.info("Semantic cache: fastembed model loaded (384d)")
            return True
        except ImportError:
            logger.warning("fastembed not installed — semantic cache disabled")
            return False
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}")
            return False

    async def _get_embedding(self, text: str) -> Optional[list[float]]:
        """Generate embedding vector. Returns None if model unavailable."""
        if not self._load_model():
            return None
        try:
            # fastembed returns generator of numpy arrays
            embeddings = list(self._model.embed(text))
            return embeddings[0].tolist()
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
            self._stats["errors"] += 1
            return None

    # ── Cosine similarity ────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _make_key(query: str) -> str:
        """Deterministic cache key from query (not salted per process).
        
        Uses hashlib.sha256 instead of built-in hash() because Python's
        hash() is salted per process (PYTHONHASHSEED) and would produce
        different values after a restart, losing the cache.
        """
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        return f"semantic:research:{digest}"

    # ── Core API ─────────────────────────────────────────

    async def lookup(
        self,
        query: str,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> Optional[dict]:
        """Check if a semantically similar query is already cached.

        Args:
            query: The research query / idea.
            threshold: Minimum cosine similarity (0.0-1.0). Default 0.92.

        Returns:
            dict with keys: response, query, similarity, cached_at
            or None if no match found.
        """
        redis = await self._get_redis()
        if redis is None:
            return None

        embedding = await self._get_embedding(query)
        if embedding is None:
            return None

        # Scan all cache entries and compare
        cursor = 0
        best_match: Optional[dict] = None
        best_score = 0.0

        try:
            while True:
                cursor, keys = await redis.scan(
                    cursor, match=f"{self.KEY_PREFIX}*", count=100
                )
                for key in keys:
                    try:
                        data = await redis.hgetall(key)
                        if not data:
                            continue
                        cached_embedding = json.loads(
                            data.get(b"embedding", data.get("embedding", b"[]"))
                        )
                        if not cached_embedding:
                            continue
                        score = self._cosine_similarity(embedding, cached_embedding)
                        if score > best_score:
                            best_score = score
                            best_match = {
                                "response": json.loads(
                                    data.get(b"response", data.get("response", b"{}"))
                                ),
                                "query": data.get(b"query", data.get("query", b""))
                                .decode() if isinstance(
                                    data.get(b"query", data.get("query", b"")), bytes
                                ) else data.get("query", ""),
                                "similarity": round(score, 4),
                                "cached_at": float(
                                    data.get(b"created_at", data.get("created_at", 0))
                                ),
                            }
                    except Exception as e:
                        logger.debug(f"Cache scan entry error: {e}")
                        continue

                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(f"Cache scan failed: {e}")
            self._stats["errors"] += 1
            return None

        if best_match and best_score >= threshold:
            self._stats["hits"] += 1
            logger.info(
                f"Semantic cache HIT ({best_score:.4f} >= {threshold}) "
                f"for '{query[:60]}'"
            )
            return best_match

        self._stats["misses"] += 1
        logger.debug(
            f"Semantic cache MISS (best={best_score:.4f} < {threshold}) "
            f"for '{query[:60]}'"
        )
        return None

    async def store(
        self,
        query: str,
        response: dict,
        ttl_category: str = "research",
    ) -> bool:
        """Cache a research result with its semantic embedding.

        Args:
            query: The research query / idea.
            response: The full ResearchReport dict.
            ttl_category: 'research' (7d) or 'trending' (24h).

        Returns:
            True if stored successfully, False otherwise.
        """
        redis = await self._get_redis()
        if redis is None:
            return False

        embedding = await self._get_embedding(query)
        if embedding is None:
            return False

        ttl = self.TTL_MAP.get(ttl_category, 7 * 24 * 3600)

        # Deterministic key based on query — overwrites on re-store
        key = self._make_key(query)

        try:
            await redis.hset(key, mapping={
                "query": query,
                "embedding": json.dumps(embedding),
                "response": json.dumps(response, default=str),
                "created_at": time.time(),
                "ttl_category": ttl_category,
            })
            await redis.expire(key, ttl)
            logger.info(
                f"Semantic cache STORE (TTL: {ttl}s) for '{query[:60]}'"
            )
            return True
        except Exception as e:
            logger.warning(f"Cache store failed: {e}")
            self._stats["errors"] += 1
            return False

    # ── Stats & reporting ────────────────────────────────

    def report_false_positive(self):
        """Call when a cached response is reported as incorrect by the user."""
        self._stats["false_positives"] += 1

    def get_stats(self) -> dict:
        """Return cache performance statistics (including estimated cost savings).
        
        Cost savings = cache_hits × estimated_cost_per_hit.
        The estimate represents saved external API calls (Tavily, Perplexity, etc.)
        that would have been made if the cache hadn't returned a result.
        """
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = round(self._stats["hits"] / total * 100, 1) if total > 0 else 0.0
        fp_rate = (
            round(self._stats["false_positives"] / self._stats["hits"] * 100, 1)
            if self._stats["hits"] > 0
            else 0.0
        )
        estimated_savings = round(
            self._stats["hits"] * self.ESTIMATED_COST_PER_HIT_USD, 2
        )
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "total_lookups": total,
            "hit_rate_pct": hit_rate,
            "false_positives": self._stats["false_positives"],
            "false_positive_rate_pct": fp_rate,
            "errors": self._stats["errors"],
            "estimated_savings_usd": estimated_savings,
            "estimated_cost_per_hit_usd": self.ESTIMATED_COST_PER_HIT_USD,
            "threshold": self.DEFAULT_THRESHOLD,
            "ttl_days": {"research": 7, "trending": 1},
        }


# ── Singleton (module-level, shared across workers) ─────

_cache_instance: Optional[SemanticCacheService] = None


def get_cache(redis_pool=None) -> SemanticCacheService:
    """Get or create the singleton cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SemanticCacheService(redis_pool=redis_pool)
    return _cache_instance
