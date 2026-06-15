"""Tavily source — primary web search + content extraction.

Handles:
- Competitor discovery via search
- Deep content extraction for competitor analysis  
- Market research via Tavily research endpoint
- All goes through Tavily API (no blocking risk)
"""

import json
import logging
import os
from typing import Optional

from ..base_source import BaseSource
from ..models import BaseSourceResult

logger = logging.getLogger(__name__)


class TavilySource(BaseSource):
    """Web search and extraction via Tavily API.
    
    Primary source for competitor discovery. Zero blocking risk.
    """
    name = "tavily"
    description = "Web search and content extraction via Tavily API"
    priority = 0  # Run first — provides baseline data
    max_concurrency = 3

    def __init__(self, http_client=None):
        super().__init__(http_client)
        self.api_key = os.getenv("TAVILY_API_KEY", "") or self._load_from_dotenv()
        self._client = self._build_httpx_client()
        self._out_of_credits = False

    def _load_from_dotenv(self) -> str:
        """Fallback: read TAVILY_API_KEY from project .env, then ~/.hermes/.env"""
        # Try project .env first
        try:
            from pathlib import Path
            project_env = Path(__file__).resolve().parent.parent.parent / ".env"
            if project_env.exists():
                import dotenv
                dotenv.load_dotenv(project_env)
        except Exception:
            pass
        key = os.getenv("TAVILY_API_KEY", "")
        if key:
            return key
        # Fallback: legacy Hermes .env
        env_path = os.path.expanduser("~/.hermes/.env")
        if not os.path.exists(env_path):
            return ""
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("TAVILY_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("\"'")
                        if val:
                            return val
        except Exception:
            pass
        return ""

    def _build_httpx_client(self):
        import httpx
        return httpx.AsyncClient(
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=60,
        )

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> BaseSourceResult:
        """Search Tavily for competitors and market data."""
        target_market = (context or {}).get("target_market", "")
        business_model = (context or {}).get("business_model", "")

        # Build targeted queries
        queries = self._build_queries(query, target_market, business_model)

        all_results = []
        sources_seen = set()

        for q in queries:
            try:
                data = await self._tavily_search(q, max_results=10)
                for r in data.get("results", []):
                    url = r.get("url", "")
                    if url and url not in sources_seen:
                        sources_seen.add(url)
                        all_results.append({
                            "title": r.get("title", ""),
                            "url": url,
                            "content": r.get("content", ""),
                            "score": r.get("score", 0),
                            "query": q,
                        })
                if self._out_of_credits:
                    break
            except Exception as e:
                logger.warning(f"Tavily search failed for '{q[:50]}': {e}")
                continue

        # Try research endpoint for deeper analysis
        research_content = ""
        try:
            research = await self._tavily_research(query, target_market)
            if research:
                research_content = research.get("content", "")
                if research.get("sources"):
                    for s in research["sources"]:
                        if isinstance(s, str) and s not in sources_seen:
                            all_results.append({
                                "title": s.split("/")[-1][:60],
                                "url": s,
                                "content": "",
                                "score": 0.5,
                                "query": "research",
                            })
        except Exception as e:
            logger.warning(f"Tavily research failed: {e}")

        return BaseSourceResult(
            source=self.name,
            success=len(all_results) > 0,
            data=all_results,
            raw_metadata={
                "queries_executed": len(queries),
                "total_results": len(all_results),
                "research_content": research_content,
            },
        )

    def _build_queries(
        self,
        idea: str,
        target_market: str = "",
        business_model: str = "",
    ) -> list[str]:
        """Build targeted search queries from the idea."""
        queries = [
            idea,
            f"{idea} startup competitors",
            f"{idea} market size",
        ]
        if target_market:
            queries.append(f"{idea} {target_market}")
            queries.append(f"{target_market} freight logistics startups")
        if business_model:
            queries.append(f"{idea} {business_model} business model")
        # Competitor-focused
        queries.append(f"top companies {idea}")
        queries.append(f"{idea} review problems complaints")
        return queries

    async def _tavily_search(
        self, query: str, max_results: int = 10
    ) -> dict:
        """Execute Tavily search."""
        import httpx
        resp = await self._client.post(
            "https://api.tavily.com/search",
            json={
                "query": query,
                "search_depth": "basic",  # cheaper (1 credit vs 2)
                "max_results": min(max_results, 20),
                "include_answer": True,
                "include_raw_content": False,
            },
        )
        if resp.status_code == 432:
            logger.warning("Tavily out of credits — skipping remaining queries")
            self._out_of_credits = True
            return {"results": [], "answer": "", "response_time": 0}
        resp.raise_for_status()
        return resp.json()

    async def _tavily_research(
        self, query: str, target_market: str = ""
    ) -> Optional[dict]:
        """Execute Tavily research endpoint (deeper analysis)."""
        topic = f"{query}"
        if target_market:
            topic += f" in {target_market}"

        resp = await self._client.post(
            "https://api.tavily.com/research",
            json={
                "input": topic,
                "model": "auto",
                "stream": False,
            },
        )
        if resp.status_code != 200:
            logger.warning(f"Tavily research returned {resp.status_code}")
            return None

        data = resp.json()
        request_id = data.get("request_id", "")
        if not request_id:
            return data

        # Poll for completion
        import asyncio
        for _ in range(30):
            await asyncio.sleep(2)
            poll = await self._client.get(
                f"https://api.tavily.com/research/{request_id}"
            )
            if poll.status_code != 200:
                continue
            status_data = poll.json()
            if status_data.get("status") == "completed":
                return status_data
            if status_data.get("status") in ("failed", "error"):
                logger.warning(f"Tavily research failed: {status_data}")
                return None

        logger.warning("Tavily research timed out")
        return None

    @classmethod
    def validate_config(cls) -> tuple[bool, str]:
        key = os.getenv("TAVILY_API_KEY", "")
        if not key:
            return False, "TAVILY_API_KEY not set in environment"
        if not key.startswith("tvly-"):
            return False, f"TAVILY_API_KEY looks invalid (starts with {key[:6]}...)"
        return True, "ok"
