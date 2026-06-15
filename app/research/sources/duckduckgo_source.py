"""DuckDuckGo source — web search without API key.

Free, no registration required. Rate-limited but works for MVP research.
Used as fallback when Tavily/Brave are unavailable.
"""

import logging
from typing import Optional

from ..base_source import BaseSource
from ..models import BaseSourceResult

logger = logging.getLogger(__name__)


class DuckDuckGoSource(BaseSource):
    """Web search via DuckDuckGo (no API key needed).
    
    Primary fallback when Tavily and Brave are unavailable.
    Rate-limited to ~1 req/s. If rate limited, waits and retries once.
    """
    name = "duckduckgo"
    description = "Web search via DuckDuckGo (free, no API key)"
    priority = 1  # After Tavily (0) and Brave (0)
    max_concurrency = 1  # DDG rate-limits hard

    def __init__(self, http_client=None):
        super().__init__(http_client)
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import httpx
            self._session = httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
                timeout=20,
                follow_redirects=True,
            )

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> BaseSourceResult:
        await self._ensure_session()
        target_market = (context or {}).get("target_market", "")

        queries = self._build_queries(query, target_market)
        all_results = []
        seen_urls = set()

        for q in queries[:4]:  # Max 4 queries to avoid rate limit
            try:
                results = await self._ddg_search(q)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
            except Exception as e:
                logger.warning(f"DuckDuckGo query failed '{q[:40]}': {e}")
                continue

        return BaseSourceResult(
            source=self.name,
            success=len(all_results) > 0,
            data=all_results,
            raw_metadata={
                "total_results": len(all_results),
                "queries_executed": min(len(queries), 4),
            },
        )

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None

    def _build_queries(self, idea: str, target_market: str = "") -> list[str]:
        queries = [
            idea,
            f"{idea} startup competitors",
            f"{idea} market size funding",
        ]
        if target_market:
            queries.append(f"{idea} {target_market}")
        queries.append(f"{idea} review problems complaints")
        return queries

    async def _ddg_search(self, query: str) -> list[dict]:
        """Search DuckDuckGo via Instant Answer API (JSON, no scraping).
        
        Falls back to HTML endpoint if instant answer returns nothing.
        """
        import asyncio
        import re
        from urllib.parse import quote

        results = []

        # ── Try Instant Answer API first (JSON, officially supported) ──
        try:
            ia_url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            resp = await self._session.get(ia_url)
            if resp.status_code == 200:
                data = resp.json()
                
                # Abstract (main result)
                if data.get("AbstractText"):
                    results.append({
                        "title": data.get("Heading", query)[:200],
                        "url": data.get("AbstractURL", ""),
                        "description": data.get("AbstractText", "")[:300],
                        "source": "duckduckgo",
                    })
                
                # Related topics
                for topic in data.get("RelatedTopics", [])[:8]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        # Extract title from the format "Title — Description"
                        text = topic.get("Text", "")
                        url = topic.get("FirstURL", "")
                        if " — " in text:
                            title, desc = text.split(" — ", 1)
                        else:
                            title = text[:80]
                            desc = text
                        results.append({
                            "title": title[:200],
                            "url": url,
                            "description": desc[:300],
                            "source": "duckduckgo",
                        })
                
                if results:
                    return results
        except Exception as e:
            logger.warning(f"DDG instant answer failed: {e}")

        # ── Fallback: HTML endpoint ──
        try:
            data = {"q": query}
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://html.duckduckgo.com",
                "Referer": "https://html.duckduckgo.com/",
            }
            resp = await self._session.post(
                "https://html.duckduckgo.com/html/",
                data=data,
                headers=headers,
            )

            if resp.status_code == 429:
                logger.warning("DuckDuckGo rate limited, waiting 5s and retrying...")
                await asyncio.sleep(5)
                resp = await self._session.post(
                    "https://html.duckduckgo.com/html/",
                    data=data,
                    headers=headers,
                )

            if resp.status_code not in (200, 202):
                logger.warning(f"DuckDuckGo returned {resp.status_code}")
                return results  # Return what we got from instant answer

            # 202 means accepted but pending — try to parse anyway
            html = resp.text
            if not html or len(html) < 100:
                return results

            # Parse DDG HTML results
            for match in re.finditer(
                r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                html, re.DOTALL,
            ):
                url = match.group(1).strip()
                title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                snippet = re.sub(r'<[^>]+>', '', match.group(3)).strip()
                if title and url:
                    results.append({
                        "title": title[:200],
                        "url": url,
                        "description": snippet[:300],
                        "source": "duckduckgo",
                    })
        except Exception as e:
            logger.warning(f"DDG HTML search failed: {e}")

        return results
