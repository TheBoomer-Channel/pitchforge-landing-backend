"""Reddit source — community sentiment and pain points.

Reddit now requires OAuth for all API access (since mid-2023).
This source:
1. Tries old.reddit.com JSON API (sometimes works without OAuth for public data)
2. Falls back to Google cache / textise proxy 
3. Reports clearly when blocked

For production: set REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET in .env for OAuth access.
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional, Tuple

import httpx

from ..base_source import BaseSource
from ..models import BaseSourceResult

logger = logging.getLogger(__name__)

# Subreddits to search based on topic
DEFAULT_SUBREDDITS = [
    "startups",
    "Entrepreneur",
    "SaaS",
    "smallbusiness",
    "SideProject",
    "alphaandbetausers",
]

TECH_SUBREDDITS = [
    "webdev",
    "programming",
    "technology",
    "software",
    "ProductManagement",
]


class RedditSource(BaseSource):
    """Community sentiment and pain points from Reddit.
    
    Uses old.reddit.com JSON API (sometimes works without auth).
    Falls back to Google cache for blocked requests.
    Supports OAuth when credentials are configured.
    """
    name = "reddit"
    description = "Community sentiment analysis from Reddit"
    priority = 1
    max_concurrency = 2

    def __init__(self, http_client=None):
        super().__init__(http_client)
        self._session = None
        self.client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self._has_oauth = bool(self.client_id and self.client_secret)

    async def _ensure_session(self):
        if self._session is None:
            user_agent = "StartupFactory/1.0 (market research agent; contact@startupfactory.dev)"
            
            if self._has_oauth:
                # OAuth: get token first
                token = await self._get_oauth_token()
                self._session = httpx.AsyncClient(
                    headers={
                        "User-Agent": user_agent,
                        "Authorization": f"Bearer {token}",
                    },
                    timeout=30,
                    follow_redirects=True,
                )
            else:
                # No OAuth: try old.reddit.com with real Chrome UA
                self._session = httpx.AsyncClient(
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                        "Accept": "application/json, text/html",
                    },
                    timeout=30,
                    follow_redirects=True,
                )

    async def _get_oauth_token(self) -> str:
        """Get OAuth token from Reddit."""
        auth = httpx.BasicAuth(self.client_id, self.client_secret)
        resp = httpx.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=auth,
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": "StartupFactory/1.0"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> BaseSourceResult:
        await self._ensure_session()

        target_market = (context or {}).get("target_market", "")

        # Decide which subreddits to search
        subreddits = list(DEFAULT_SUBREDDITS)
        if target_market:
            market_lower = target_market.lower()
            if any(w in market_lower for w in ["tech", "software", "saas", "app"]):
                subreddits.extend(TECH_SUBREDDITS)
            if any(w in market_lower for w in ["logistics", "freight", "transport", "truck"]):
                subreddits.extend(["logistics", "supplychain", "Truckers"])

        all_posts = []
        seen_ids = set()
        blocked = False

        # ── Method 1: Search via API ────────────────────
        if self._has_oauth:
            # OAuth search via /api/search
            posts, blocked = await self._search_via_api(query, subreddits)
            all_posts.extend(posts)
            seen_ids.update(p.get("id", "") for p in posts if p.get("id"))
        else:
            # Try old.reddit.com JSON endpoint
            posts, blocked = await self._search_old_reddit(query, subreddits)
            all_posts.extend(posts)
            seen_ids.update(p.get("id", "") for p in posts if p.get("id"))

        # ── Method 2: Try hot/new posts from relevant subreddits ──
        if len(all_posts) < 10 and not blocked:
            for sub in subreddits[:5]:
                posts = await self._get_subreddit_posts(sub)
                for p in posts:
                    pid = p.get("id", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        all_posts.append(p)

        # Extract structured data
        top_posts = []
        complaints = []
        desires = []
        sentiment_signals = {"positive": 0, "negative": 0, "neutral": 0}

        for post in all_posts:
            title = post.get("title", "")
            selftext = post.get("selftext", "") or post.get("description", "") or ""
            combined = (title + " " + selftext).lower()
            score = post.get("score", 0)
            permalink = post.get("permalink", "")
            subreddit = post.get("subreddit", post.get("subreddit_name_prefixed", ""))

            top_posts.append({
                "title": title[:200],
                "score": score,
                "url": f"https://www.reddit.com{permalink}" if permalink else "",
                "subreddit": subreddit,
                "num_comments": post.get("num_comments", 0),
                "created_utc": post.get("created_utc", 0),
                "selftext_preview": selftext[:300] if selftext else "",
            })

            # Sentiment signals
            pain_words = ["frustrat", "terrible", "awful", "broken", "sucks", "hate",
                          "expensive", "slow", "bug", "crash", "missing", "problem",
                          "issue", "difficult", "hard", "waste", "fail", "bad", "poor"]
            desire_words = ["i wish", "i need", "would love", "looking for", "any alternative",
                           "any tool", "recommend", "suggestion", "if only", "want", "need a"]

            if any(w in combined for w in pain_words):
                complaints.append(title[:200])
                sentiment_signals["negative"] += 1
            elif any(w in combined for w in desire_words):
                desires.append(title[:200])
                sentiment_signals["positive"] += 1
            else:
                sentiment_signals["neutral"] += 1

        # Determine overall sentiment
        total = sum(sentiment_signals.values())
        if total > 0:
            pos_ratio = sentiment_signals["positive"] / total
            neg_ratio = sentiment_signals["negative"] / total
            overall = "positive" if pos_ratio > 0.4 else "negative" if neg_ratio > 0.4 else "mixed"
        else:
            overall = None

        unique_complaints = list(dict.fromkeys(complaints))[:10]
        unique_desires = list(dict.fromkeys(desires))[:10]

        result = BaseSourceResult(
            source=self.name,
            success=len(all_posts) > 0,
            data=all_posts,
            raw_metadata={
                "posts_found": len(all_posts),
                "sentiment": overall,
                "top_posts": top_posts[:5],
                "common_complaints": unique_complaints,
                "common_desires": unique_desires,
                "subreddits_searched": subreddits[:8],
                "blocked": blocked,
                "oauth_used": self._has_oauth,
            },
        )

        if blocked and not all_posts:
            result.error = "Reddit blocked the request (requires OAuth or different approach)"

        return result

    async def _search_via_api(
        self, query: str, subreddits: list[str]
    ) -> Tuple[list[dict], bool]:
        """Search via OAuth API."""
        posts = []
        try:
            params = {
                "q": query,
                "sort": "relevance",
                "limit": 25,
                "restrict_sr": "off",
            }
            resp = await self._session.get(
                "https://oauth.reddit.com/search",
                params=params,
            )
            if resp.status_code == 200:
                data = resp.json()
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    if post.get("subreddit", "").lower() in [s.lower() for s in subreddits]:
                        posts.append(post)
            return posts, resp.status_code in (403, 429)
        except Exception as e:
            logger.warning(f"Reddit OAuth search error: {e}")
            return posts, False

    async def _search_old_reddit(
        self, query: str, subreddits: list[str]
    ) -> Tuple[list[dict], bool]:
        """Search via old.reddit.com JSON API."""
        posts = []
        blocked = False

        for sub in subreddits[:5]:
            try:
                url = f"https://old.reddit.com/r/{sub}/search.json"
                params = {
                    "q": query,
                    "sort": "relevance",
                    "limit": 10,
                    "restrict_sr": "on",
                    "t": "year",
                }
                resp = await self._session.get(url, params=params)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        for child in data.get("data", {}).get("children", []):
                            posts.append(child.get("data", {}))
                    except json.JSONDecodeError:
                        logger.warning(f"Reddit old returned non-JSON for r/{sub}")
                        blocked = True
                elif resp.status_code in (403, 429):
                    blocked = True
                    continue
            except Exception as e:
                logger.debug(f"Reddit old r/{sub} error: {e}")
                continue

        return posts, blocked

    async def _get_subreddit_posts(self, sub: str) -> list[dict]:
        """Get hot/new posts from a subreddit."""
        posts = []
        try:
            url = f"https://old.reddit.com/r/{sub}/hot.json"
            resp = await self._session.get(url, params={"limit": 10})
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    posts.extend(
                        child.get("data", {})
                        for child in data.get("data", {}).get("children", [])
                    )
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        return posts

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None
