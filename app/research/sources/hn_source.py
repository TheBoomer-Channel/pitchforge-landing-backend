"""Hacker News source — tech community signal and sentiment.

Uses HN Algolia API (rate limit: 10,000 req/h, no auth needed).
Perfect for detecting if a problem/solution resonates with technical audience.
"""

import json
import logging
from typing import Optional

from ..base_source import BaseSource
from ..models import BaseSourceResult

logger = logging.getLogger(__name__)

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
HN_ALGOLIA_TAGS_URL = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNewsSource(BaseSource):
    """Hacker News mentions, sentiment, and discussion analysis.
    
    Uses Algolia's HN API — no blocking risk, generous rate limits.
    Searches for query-related stories and Show HN / Ask HN posts.
    """
    name = "hacker_news"
    description = "Tech community signal and sentiment from Hacker News"
    priority = 2
    max_concurrency = 2

    def __init__(self, http_client=None):
        super().__init__(http_client)
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import httpx
            self._session = httpx.AsyncClient(
                headers={"User-Agent": "StartupFactory/1.0 research agent"},
                timeout=30,
            )

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> BaseSourceResult:
        await self._ensure_session()

        # Build search queries
        queries = [
            query,
            f"Show HN {query}",
            f"Ask HN {query}",
        ]

        all_hits = []
        seen_ids = set()

        for q in queries:
            try:
                params = {
                    "query": q,
                    "hitsPerPage": 20,
                    "tags": None if q.startswith(("Show HN", "Ask HN")) else "story",
                }
                if q.startswith("Show HN"):
                    params["tags"] = "show_hn"
                elif q.startswith("Ask HN"):
                    params["tags"] = "ask_hn"

                resp = await self._session.get(HN_ALGOLIA_URL, params=params)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                for hit in data.get("hits", []):
                    hid = hit.get("objectID", "")
                    if hid and hid not in seen_ids:
                        seen_ids.add(hid)
                        all_hits.append(hit)

            except Exception as e:
                logger.warning(f"HN search error for '{q[:40]}': {e}")
                continue

        # Extract structured metadata
        top_posts = []
        points_total = 0
        comments_total = 0

        for hit in all_hits:
            title = hit.get("title", "")
            points = hit.get("points", 0) or 0
            comments = hit.get("num_comments", 0) or 0
            url = hit.get("url") or hit.get("story_url") or ""
            hn_url = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            author = hit.get("author", "")

            top_posts.append({
                "title": title[:200],
                "points": points,
                "num_comments": comments,
                "url": url,
                "hn_url": hn_url,
                "author": author,
                "created_at": hit.get("created_at", ""),
                "_tags": hit.get("_tags", []),
            })
            points_total += points
            comments_total += comments

        # Classify sentiment from titles
        positive_signals = []
        negative_signals = []
        for hit in all_hits:
            title_lower = (hit.get("title", "") + " " + (hit.get("comment_text", "") or "")).lower()
            if any(w in title_lower for w in ["show hn:", "launch", "built", "made", "open source"]):
                positive_signals.append(hit.get("title", "")[:200])
            if any(w in title_lower for w in ["looking for", "ask hn:", "alternatives to", "recommend"]):
                negative_signals.append(hit.get("title", "")[:200])

        # Sentiment heuristic
        if points_total > 0 and len(all_hits) > 0:
            avg_points = points_total / len(all_hits)
            if avg_points > 50:
                signal = "strong_interest"
            elif avg_points > 15:
                signal = "moderate_interest"
            elif avg_points > 3:
                signal = "low_interest"
            else:
                signal = "minimal"
        else:
            signal = "no_mentions"

        return BaseSourceResult(
            source=self.name,
            success=len(all_hits) > 0,
            data=all_hits,
            raw_metadata={
                "mentions": len(all_hits),
                "total_points": points_total,
                "total_comments": comments_total,
                "signal_level": signal,
                "top_posts": top_posts[:5],
                "show_hn_count": sum(
                    1 for h in all_hits if "show_hn" in h.get("_tags", [])
                ),
                "ask_hn_count": sum(
                    1 for h in all_hits if "ask_hn" in h.get("_tags", [])
                ),
                "positive_signals": positive_signals[:3],
                "negative_signals": negative_signals[:3],
            },
        )

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None
