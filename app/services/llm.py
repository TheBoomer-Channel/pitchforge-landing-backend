"""
DeepSeek LLM Client — unified interface for DeepSeek API.

Models:
- deepseek-chat (Flash/v4-flash): fast, cheap, for code gen + long context
- deepseek-reasoner (Pro/v4-pro): complex reasoning, design, planning

Usage:
    from app.services.llm import llm

    # Quick chat (Flash)
    result = await llm.chat("Generate a PRD for X")

    # Complex reasoning (Pro)
    result = await llm.pro("Analyze market positioning for...")

    # JSON mode
    result = await llm.json("Return JSON with competitor analysis...")

Cost tracking (TASK-026):
    Every API call is automatically recorded to `llm_costs` collection
    via `LLMCostTracker`. Costs are calculated using per-model pricing
    from `app.services.llm_cost_tracker.PRICING`.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from dotenv import load_dotenv
from .llm_cost_tracker import cost_tracker, calculate_cost

# Resolve .env relative to project root, not CWD (works regardless of where you run from)
# llm.py is at code/backend/app/services/ → 3 levels up = code/backend/ (where .env lives)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # Fallback: try CWD (for Docker where .env is in /app)
    load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com"

FLASH_MODEL = "deepseek-chat"       # v4-flash — fast, cheap, code gen
PRO_MODEL = "deepseek-reasoner"     # v4-pro — complex reasoning, planning

DEFAULT_TIMEOUT = 180  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds base delay


class DeepSeekLLM:
    """Async DeepSeek API client with retries and model routing."""

    def __init__(self, api_key: str = "", base_url: str = DEEPSEEK_BASE):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._flash_model = FLASH_MODEL
        self._pro_model = PRO_MODEL

        if not self.api_key:
            logger.warning(
                "DEEPSEEK_API_KEY not set — LLM calls will fail. "
                "Set it in code/backend/.env"
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init httpx client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(DEFAULT_TIMEOUT, connect=15.0),
            )
        return self._client

    async def close(self):
        """Clean up HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Public API ──────────────────────────────────────

    async def chat(
        self,
        prompt: str,
        *,
        model: str = "",
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> str:
        """Send a chat completion. Uses Flash by default."""
        return await self._complete(
            model=model or self._flash_model,
            messages=self._build_messages(prompt, system=system),
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def pro(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: int = 300,
    ) -> str:
        """Send a completion using Pro (deepseek-reasoner) for complex tasks."""
        return await self._complete(
            model=self._pro_model,
            messages=self._build_messages(prompt, system=system),
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def json(
        self,
        prompt: str,
        *,
        model: str = "",
        system: str = "You are a precise JSON generator. Output ONLY valid JSON, no markdown, no explanation.",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> Optional[dict]:
        """Get a JSON response, parsed automatically."""
        result = await self._complete(
            model=model or self._flash_model,
            messages=self._build_messages(prompt, system=system),
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return self._extract_json(result)

    async def json_pro(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 8192,
        timeout: int = 300,
    ) -> Optional[dict]:
        """Get a JSON response from Pro model."""
        if not system:
            system = "You are a precise JSON generator. Output ONLY valid JSON, no markdown, no explanation."
        return await self.json(
            prompt,
            model=self._pro_model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    # ── Core Implementation ─────────────────────────────

    async def _complete(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        timeout: int,
    ) -> str:
        """Send completion with retries and cost tracking (TASK-026).

        After a successful response, records token usage and cost
        to the `llm_costs` collection via LLMCostTracker.
        """
        if not self.api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY not configured. Set it in code/backend/.env"
            )

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                client = await self._get_client()
                response = await client.post(
                    "/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                    timeout=httpx.Timeout(timeout, connect=15.0),
                )

                if response.status_code == 429:
                    # Rate limited — exponential backoff
                    delay = RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"DeepSeek rate limited (attempt {attempt+1}), waiting {delay}s")
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 500:
                    # Server error — retry
                    delay = RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"DeepSeek server error {response.status_code} (attempt {attempt+1}), waiting {delay}s")
                    await asyncio.sleep(delay)
                    continue

                if response.status_code != 200:
                    error_body = response.text[:500]
                    raise RuntimeError(
                        f"DeepSeek API error {response.status_code}: {error_body}"
                    )

                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError("DeepSeek returned empty choices")

                content = choices[0].get("message", {}).get("content", "")

                # ── Cost Tracking (TASK-026) ──────────
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                cached_tokens = usage.get("prompt_cache_hit_tokens", 0)

                if prompt_tokens > 0 or completion_tokens > 0:
                    try:
                        cost_usd = calculate_cost(
                            model=model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            cached_prompt_tokens=cached_tokens,
                        )
                        await cost_tracker.record(
                            provider="deepseek",
                            model=model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            cost_usd=cost_usd,
                            metadata={"task_type": "chat"},
                        )
                        logger.debug(
                            f"Cost tracked: {model} "
                            f"{prompt_tokens}+{completion_tokens}tks "
                            f"${cost_usd:.6f}"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record LLM cost (non-fatal): {e}")

                if not content:
                    logger.warning("DeepSeek returned empty content")
                    return ""

                return content.strip()

            except (httpx.TimeoutException, httpx.ReadTimeout) as e:
                last_error = e
                logger.warning(f"DeepSeek timeout (attempt {attempt+1})")
                await asyncio.sleep(RETRY_DELAY)
                continue

            except httpx.ConnectError as e:
                last_error = e
                logger.warning(f"DeepSeek connection error (attempt {attempt+1})")
                await asyncio.sleep(RETRY_DELAY * 2)
                continue

        raise RuntimeError(
            f"DeepSeek failed after {MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        )

    # ── Helpers ─────────────────────────────────────────

    @staticmethod
    def _build_messages(prompt: str, system: str = "") -> list[dict]:
        """Build messages array for the API."""
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extract JSON from LLM response (handles markdown fences)."""
        if not text:
            return None

        # Try to find JSON block
        start = text.find("```json")
        if start >= 0:
            start += 7
            end = text.find("```", start)
            if end >= 0:
                text = text[start:end].strip()

        # Try to find raw JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try cleaning common issues
            cleaned = text.replace("\n", " ").replace("\r", "")
            cleaned = cleaned.replace(", }", " }").replace(", ]", " ]")
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from: {text[:200]}...")
                return None


# ── Singleton ───────────────────────────────────────────

_llm_instance: Optional[DeepSeekLLM] = None


def get_llm() -> DeepSeekLLM:
    """Get or create the DeepSeek LLM singleton."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = DeepSeekLLM()
    return _llm_instance


# Shortcut for imports
llm = get_llm()
