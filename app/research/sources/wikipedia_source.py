"""Wikipedia source — structured data about established competitors.

Uses Wikimedia API (no auth, no rate limits, no blocking).
Great for getting factual data about known companies: funding, founders, history.
"""

import json
import logging
from typing import Optional

from ..base_source import BaseSource
from ..models import BaseSourceResult

logger = logging.getLogger(__name__)

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARIES = [
    "https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
]


class WikipediaSource(BaseSource):
    """Extract structured data about competitors from Wikipedia.
    
    Zero blocking risk (public API, no auth, documented rate: 200 req/s).
    Gets: founding date, founders, funding, business model, market presence.
    """
    name = "wikipedia"
    description = "Structured company/industry data from Wikipedia"
    priority = 2
    max_concurrency = 5

    def __init__(self, http_client=None):
        super().__init__(http_client)
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import httpx
            self._session = httpx.AsyncClient(
                headers={"User-Agent": "StartupFactory/1.0 (research agent)"},
                timeout=30,
            )

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> BaseSourceResult:
        await self._ensure_session()

        target_market = (context or {}).get("target_market", "")

        # First: search for relevant Wikipedia pages
        search_terms = [
            query,
            f"{query} company",
            f"{query} industry",
        ]
        if target_market:
            search_terms.append(f"{target_market}")

        found_titles = set()
        all_data = []

        for term in search_terms[:3]:
            titles = await self._search_wikipedia(term, limit=5)
            found_titles.update(titles)

        # Fetch summaries for each unique title
        for title in found_titles:
            try:
                summary = await self._get_summary(title)
                if summary and summary.get("extract"):
                    all_data.append({
                        "title": summary.get("title", title),
                        "extract": summary.get("extract", ""),
                        "url": summary.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        "page_id": summary.get("pageid"),
                        "thumbnail": summary.get("thumbnail", {}).get("source") if summary.get("thumbnail") else None,
                    })
            except Exception as e:
                logger.debug(f"Wiki summary error for '{title}': {e}")
                continue

        # Also search for 'List of' pages (industry overviews)
        list_titles = []
        for term in search_terms[:2]:
            list_q = f"List of {term} companies"
            titles = await self._search_wikipedia(list_q, limit=3)
            list_titles.extend(titles)

        for title in list_titles:
            try:
                extract = await self._get_extract(title)
                if extract:
                    all_data.append({
                        "title": f"[List] {title}",
                        "extract": extract[:2000],
                        "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                        "type": "industry_list",
                    })
            except Exception as e:
                logger.debug(f"Wiki list error for '{title}': {e}")
                continue

        return BaseSourceResult(
            source=self.name,
            success=len(all_data) > 0,
            data=all_data,
            raw_metadata={
                "pages_found": len(found_titles),
                "total_extracts": len(all_data),
                "titles_searched": list(found_titles)[:10],
            },
        )

    async def _search_wikipedia(
        self, query: str, limit: int = 5
    ) -> set[str]:
        """Search Wikipedia and return page titles."""
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": limit,
            "srprop": "titlesnippet",
        }
        try:
            resp = await self._session.get(WIKI_API, params=params)
            if resp.status_code != 200:
                return set()
            data = resp.json()
            return {
                r["title"]
                for r in data.get("query", {}).get("search", [])
            }
        except Exception as e:
            logger.warning(f"Wiki search error: {e}")
            return set()

    async def _get_summary(self, title: str) -> Optional[dict]:
        """Get page summary via REST API."""
        import httpx
        safe_title = title.replace(" ", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_title}"
        try:
            resp = await self._session.get(url)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    async def _get_extract(self, title: str) -> Optional[str]:
        """Get full page extract via action API."""
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "format": "json",
        }
        try:
            resp = await self._session.get(WIKI_API, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for _, page in pages.items():
                return page.get("extract", "")
        except Exception:
            pass
        return None

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None
