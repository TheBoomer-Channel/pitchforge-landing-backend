"""Brave Search API source — web search via Brave (free tier: 2000 queries/month).

Requires BRAVE_API_KEY env var. Get one free at https://brave.com/search/api/

Returns web search results with titles, URLs, descriptions, and age.
"""

import logging
import os
from typing import Optional

from ..base_source import BaseSource
from ..models import BaseSourceResult

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSource(BaseSource):
    """Web search via Brave Search API.
    
    Requires BRAVE_API_KEY in environment (free tier: 2000 queries/month).
    """
    name = "brave"
    description = "Web search via Brave Search API"
    priority = 0  # Runs early — provides baseline competitor data
    max_concurrency = 2

    def __init__(self, http_client=None):
        super().__init__(http_client)
        self.api_key = os.getenv("BRAVE_API_KEY", "")
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import httpx
            self._session = httpx.AsyncClient(
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self.api_key,
                },
                timeout=30,
            )

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> BaseSourceResult:
        if not self.api_key:
            return BaseSourceResult(
                source=self.name,
                success=False,
                error="BRAVE_API_KEY not configured. Get one free at https://brave.com/search/api/",
            )

        await self._ensure_session()
        target_market = (context or {}).get("target_market", "")

        queries = self._build_queries(query, target_market)
        all_results = []
        seen_urls = set()

        for q in queries[:4]:
            try:
                results = await self._brave_search(q)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
            except Exception as e:
                logger.warning(f"Brave search failed for '{q[:40]}': {e}")
                continue

        return BaseSourceResult(
            source=self.name,
            success=len(all_results) > 0,
            data=all_results,
            raw_metadata={
                "total_results": len(all_results),
                "queries_executed": len(queries[:4]),
                "has_api_key": bool(self.api_key),
            },
        )

    def _build_queries(self, idea: str, target_market: str = "") -> list[str]:
        queries = [
            idea,
            f"{idea} startup competitors alternatives",
            f"{idea} market size funding",
        ]
        if target_market:
            queries.append(f"{idea} {target_market}")
        queries.append(f"{idea} review problems complaints pricing")
        return queries

    async def _brave_search(self, query: str) -> list[dict]:
        """Execute Brave Search API query."""
        params = {
            "q": query,
            "count": 10,
            "offset": 0,
            "safesearch": "off",
            "freshness": "py",  # past year
        }
        resp = await self._session.get(BRAVE_SEARCH_URL, params=params)
        
        if resp.status_code == 401:
            logger.warning("Brave API: invalid or missing API key")
            return []
        if resp.status_code == 429:
            logger.warning("Brave API: rate limited")
            return []
        
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "age": item.get("age", ""),
                "source": "brave",
            })

        return results

    @classmethod
    def validate_config(cls) -> tuple[bool, str]:
        key = os.getenv("BRAVE_API_KEY", "")
        if not key:
            return False, "BRAVE_API_KEY not set. Get one free at https://brave.com/search/api/"
        return True, "ok"
