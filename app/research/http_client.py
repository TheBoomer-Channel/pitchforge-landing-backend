"""Tiered HTTP client with anti-blocking progressive fallback.

Architecture:
  Tier 1 → httpx + real Chrome UA + cookie persistence → 90% of sites
  Tier 2 → Playwright stealth (human_browser.py subprocess) → Cloudflare sites
  Tier 3 → Tavily extract endpoint → universal fallback

Usage:
    client = await ResearchHTTPClient.create()
    html = await client.get_text("https://example.com")
    json_data = await client.get_json("https://api.example.com/data")
"""

import asyncio
import json
import logging
import os
import random
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

from opentelemetry import trace

import httpx

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# ── Real Chrome User-Agents (rotated) ──────────────────

CHROME_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]


# ── Cookie Jar ──────────────────────────────────────────

COOKIE_DIR = Path(tempfile.gettempdir()) / "research_http_cookies"


def _ensure_cookie_dir():
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)


def _cookie_path(domain: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9.-]", "_", domain)
    return COOKIE_DIR / f"{safe}.json"


def _load_cookies(domain: str) -> dict:
    path = _cookie_path(domain)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _save_cookies(domain: str, cookies: dict):
    _ensure_cookie_dir()
    path = _cookie_path(domain)
    try:
        path.write_text(json.dumps(cookies, indent=2))
    except Exception:
        pass


# ── Tiered HTTP Client ─────────────────────────────────

class ResearchHTTPClient:
    """Async HTTP client with progressive anti-blocking."""

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 2,
        respect_robots: bool = False,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._client: Optional[httpx.AsyncClient] = None
        self._domain_last_access: dict[str, float] = {}
        self._tavily_api_key: Optional[str] = None

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self):
        if self._client is None:
            ua = random.choice(CHROME_UAS)
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                },
                follow_redirects=True,
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        if not self._tavily_api_key:
            self._tavily_api_key = os.getenv("TAVILY_API_KEY", "")

    def _politely_wait(self, url: str):
        """Wait between requests to same domain (anti-blocking)."""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        now = time.monotonic()
        last = self._domain_last_access.get(domain, 0)
        elapsed = now - last
        needed = random.uniform(self.min_delay, self.max_delay)
        if elapsed < needed:
            time.sleep(needed - elapsed)
        self._domain_last_access[domain] = time.monotonic()

    # ── Tier 1: httpx ───────────────────────────────────
    
    async def get_text(self, url: str, **kwargs) -> tuple[str, str]:
        """Fetch URL text content. Returns (content, source_tier).
        
        Raises httpx.HTTPStatusError on non-2xx.
        """
        await self._ensure_client()
        self._politely_wait(url)

        domain = self._domain_from_url(url)
        cookies = _load_cookies(domain)

        # OTel span for this HTTP request
        with tracer.start_as_current_span(
            f"HTTP {url[:60]}",
            attributes={
                "http.url": url[:200],
                "http.method": "GET",
                "http.domain": domain,
            },
        ) as span:
            for attempt in range(1 + self.max_retries):
                try:
                    resp = await self._client.get(
                        url,
                        cookies=cookies,
                        **kwargs,
                    )
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", "5"))
                        logger.warning(f"429 on {url[:60]}, retrying after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status_code == 403:
                        raise httpx.HTTPStatusError(
                            f"403 Forbidden: {url[:80]}", request=resp.request, response=resp
                        )
                    resp.raise_for_status()
                    
                    span.set_attribute("http.status_code", resp.status_code)
                    span.set_attribute("http.content_length", len(resp.text))
                    
                    # Save cookies from response
                    if resp.cookies:
                        _save_cookies(domain, dict(resp.cookies))
                    
                    return resp.text, "httpx"
                    
                except httpx.TimeoutException:
                    span.set_attribute("http.retry", attempt + 1)
                    if attempt < self.max_retries:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise
                except httpx.HTTPStatusError as e:
                    span.set_attribute("http.status_code", e.response.status_code if e.response else 0)
                    span.record_exception(e)
                    raise

            raise httpx.HTTPStatusError(
                f"Max retries exhausted for {url[:80]}", 
                request=None, response=None  # type: ignore
            )

    async def get_json(self, url: str, **kwargs) -> tuple[dict, str]:
        """Fetch JSON from URL. Returns (parsed_dict, source_tier)."""
        content, tier = await self.get_text(url, **kwargs)
        return json.loads(content), tier

    async def get_soup(self, url: str, **kwargs):
        """Fetch URL and return BeautifulSoup. Requires bs4 installed."""
        from bs4 import BeautifulSoup
        html, tier = await self.get_text(url, **kwargs)
        return BeautifulSoup(html, "lxml"), tier

    # ── Tier 2: Playwright Stealth (fallback) ─────────

    async def get_text_stealth(self, url: str, timeout: float = 60) -> tuple[str, str]:
        """Use Playwright stealth for Cloudflare/JS-heavy sites.
        
        Spawns human_browser.py as subprocess.
        """
        script = os.path.expanduser(
            os.environ.get(
                "HUMAN_BROWSER_SCRIPT",
                "~/.hermes/profiles/swarm1/skills/human-browser/scripts/human_browser.py",
            )
        )
        if not os.path.exists(script):
            logger.warning("human_browser.py not found, falling back to httpx retry")
            return await self.get_text(url)

        proc = await asyncio.create_subprocess_exec(
            "python3", script, url, "10",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise httpx.TimeoutException(f"Stealth timeout on {url[:60]}")

        if proc.returncode != 0:
            raise httpx.HTTPStatusError(
                f"Stealth failed ({proc.returncode}): {stderr.decode()[:200]}",
                request=None, response=None,
            )

        return stdout.decode(), "stealth"

    # ── Tier 3: Tavily Extract (universal fallback) ─────

    async def get_text_via_tavily(self, url: str) -> tuple[str, str]:
        """Use Tavily extract endpoint as last resort.
        
        Works even when both httpx and stealth are blocked.
        """
        if not self._tavily_api_key:
            raise ValueError("TAVILY_API_KEY not set, cannot use Tavily fallback")

        await self._ensure_client()
        resp = await self._client.post(
            "https://api.tavily.com/extract",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._tavily_api_key}",
            },
            json={"urls": [url]},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        
        results = data.get("results", [])
        if results and results[0].get("raw_content"):
            return results[0]["raw_content"], "tavily_extract"
        
        # Fallback: maybe it returned a different field
        extracted = data.get("extracted_content", "")
        if extracted:
            return extracted, "tavily_extract"
            
        raise ValueError(f"Tavily extract returned no content for {url[:60]}")

    # ── Unified fetch with auto-fallback ────────────────

    async def fetch(self, url: str, tier_limit: int = 3) -> tuple[str, str]:
        """Fetch a URL with progressive fallback through tiers.
        
        Args:
            url: The URL to fetch.
            tier_limit: Max tier to attempt (1=httpx, 2=+stealth, 3=+tavily)
        
        Returns: (content, tier_name)
        """
        tiers = [
            ("httpx", self.get_text, 1),
            ("stealth", self.get_text_stealth, 2),
            ("tavily_extract", self.get_text_via_tavily, 3),
        ]

        last_error = None
        for name, method, tier in tiers:
            if tier > tier_limit:
                break
            try:
                return await method(url)
            except Exception as e:
                logger.info(f"Tier {tier} ({name}) failed for {url[:60]}: {e}")
                last_error = e
                continue

        raise RuntimeError(
            f"All tiers exhausted for {url[:60]}. Last error: {last_error}"
        )

    # ── Helpers ─────────────────────────────────────────

    @staticmethod
    def _domain_from_url(url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
