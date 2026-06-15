"""GitHub source — discover similar open-source projects and tools.

Uses GitHub REST API. Without token: 60 req/h. With token: 5,000 req/h.
Reads GITHUB_TOKEN from env if available.
"""

import json
import logging
import os
from typing import Optional

from ..base_source import BaseSource
from ..models import BaseSourceResult

logger = logging.getLogger(__name__)

GH_API = "https://api.github.com"


class GitHubSource(BaseSource):
    """Discover similar open-source projects and tools on GitHub.
    
    Searches for repositories related to the idea.
    Extracts: stars, description, topics, recent activity.
    """
    name = "github"
    description = "Open-source project discovery via GitHub API"
    priority = 3
    max_concurrency = 2

    def __init__(self, http_client=None):
        super().__init__(http_client)
        self.token = os.getenv("GITHUB_TOKEN", "")
        self._session = None

    async def _ensure_session(self):
        if self._session is None:
            import httpx
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "StartupFactory/1.0",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._session = httpx.AsyncClient(headers=headers, timeout=30)

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> BaseSourceResult:
        await self._ensure_session()

        target_market = (context or {}).get("target_market", "")

        # Build search queries
        search_queries = [
            query,
            f"{query} tool",
            f"{query} platform",
        ]
        if target_market:
            search_queries.append(f"{query} {target_market}")

        all_repos = []
        seen_ids = set()

        for q in search_queries:
            try:
                params = {
                    "q": q,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": 10,
                }
                resp = await self._session.get(
                    f"{GH_API}/search/repositories",
                    params=params,
                )
                if resp.status_code == 403:
                    logger.warning("GitHub API rate limited")
                    break
                if resp.status_code != 200:
                    continue

                data = resp.json()
                for item in data.get("items", []):
                    rid = item.get("id")
                    if rid and rid not in seen_ids:
                        seen_ids.add(rid)
                        all_repos.append({
                            "name": item.get("full_name", ""),
                            "description": item.get("description", "") or "",
                            "stars": item.get("stargazers_count", 0),
                            "forks": item.get("forks_count", 0),
                            "language": item.get("language"),
                            "topics": item.get("topics", []),
                            "url": item.get("html_url", ""),
                            "created_at": item.get("created_at", ""),
                            "updated_at": item.get("updated_at", ""),
                            "license": item.get("license", {}).get("spdx_id") if item.get("license") else None,
                        })

            except Exception as e:
                logger.warning(f"GitHub search error for '{q[:40]}': {e}")
                continue

        # Sort by stars descending
        all_repos.sort(key=lambda r: r.get("stars", 0), reverse=True)

        # Extract metadata
        total_stars = sum(r.get("stars", 0) for r in all_repos)
        languages = {}
        for r in all_repos:
            lang = r.get("language")
            if lang:
                languages[lang] = languages.get(lang, 0) + 1

        return BaseSourceResult(
            source=self.name,
            success=len(all_repos) > 0,
            data=all_repos,
            raw_metadata={
                "repos_found": len(all_repos),
                "total_stars": total_stars,
                "languages": languages,
                "top_repos": all_repos[:5],
                "has_token": bool(self.token),
            },
        )

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None
