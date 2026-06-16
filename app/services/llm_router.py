"""LLM Router — multi-model LLM abstraction with circuit breaker and fallback.

TASK-056 — Multi-Model LLM con Fallback.

Design:
- Priority-based model selection per task type
- Circuit breaker per model: after 5 errors in 60s, skip for 300s
- Fallback chain: primary → secondary → tertiary → last resort
- A/B routing: pitch → Claude 3.5, pricing → GPT-4o, code → DeepSeek Flash
- Cost tracking integrated with existing LLMCostTracker
- Degrades gracefully when providers fail

Usage:
    from app.services.llm_router import llm_router

    # Default chat (auto-selects best model)
    result = await llm_router.chat("Generate a PRD for X")

    # Task-specific routing
    result = await llm_router.chat("...", task_type="pitch")
    result = await llm_router.chat("...", task_type="pricing")

    # Get router status
    status = llm_router.get_status()
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

from dotenv import load_dotenv
from .llm_cost_tracker import cost_tracker

# Resolve .env relative to project root
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

logger = logging.getLogger(__name__)


# ── Task Types ─────────────────────────────────────────

class TaskType(str, Enum):
    CHAT = "chat"                # General chat / quick answers
    CODE = "code"               # Code generation (cheap, fast)
    PITCH = "pitch"             # Pitch deck narrative (quality > cost)
    PRICING = "pricing"         # Pricing analysis (precision)
    PLANNING = "planning"       # Complex planning/architecture
    RESEARCH = "research"       # Research synthesis
    JSON = "json"               # JSON output


# ── Model Config ───────────────────────────────────────

@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    name: str                    # Model identifier (e.g. "gpt-4o")
    provider: str                # Provider name (e.g. "openai", "anthropic")
    api_key_env: str             # Environment variable for API key
    base_url: str                # API base URL
    priority: int = 5            # Lower = preferred (1 = best)
    cost_per_1k_input: float = 0.005   # USD per 1K input tokens
    cost_per_1k_output: float = 0.015  # USD per 1K output tokens
    max_tokens: int = 8192       # Max output tokens
    default_temperature: float = 0.3
    model_id: str = ""           # API model identifier (defaults to name)


# ── Circuit Breaker State ──────────────────────────────

@dataclass
class CircuitBreaker:
    """Per-model circuit breaker state."""
    failure_count: int = 0
    first_failure_at: float = 0.0
    open_until: float = 0.0      # Circuit open until this timestamp
    consecutive_successes: int = 0
    total_calls: int = 0
    total_failures: int = 0
    total_latency_ms: float = 0.0

    FAILURE_THRESHOLD = 5        # 5 failures
    FAILURE_WINDOW = 60          # within 60 seconds
    COOLDOWN = 300               # skip for 300 seconds (5 min)
    HALF_OPEN_SUCCESSES = 3      # 3 consecutive successes to close

    @property
    def is_open(self) -> bool:
        if self.open_until > time.time():
            return True
        if self.open_until > 0 and self.open_until <= time.time():
            # Half-open: allow a probe request
            return False
        return False

    def record_failure(self):
        now = time.time()
        self.total_failures += 1
        self.total_calls += 1
        self.consecutive_successes = 0

        if self.failure_count == 0:
            self.first_failure_at = now
            self.failure_count = 1
        else:
            # Reset window if too old
            if now - self.first_failure_at > self.FAILURE_WINDOW:
                self.first_failure_at = now
                self.failure_count = 1
            else:
                self.failure_count += 1

        # Open circuit if threshold exceeded
        if self.failure_count >= self.FAILURE_THRESHOLD:
            self.open_until = now + self.COOLDOWN
            logger.warning(
                f"Circuit breaker OPEN for model "
                f"({self.failure_count} failures in {self.FAILURE_WINDOW}s, "
                f"cooldown {self.COOLDOWN}s)"
            )

    def record_success(self, latency_ms: float):
        self.total_calls += 1
        self.total_latency_ms += latency_ms
        self.consecutive_successes += 1
        self.failure_count = 0

        # Close circuit after enough half-open successes
        if self.open_until > 0 and self.consecutive_successes >= self.HALF_OPEN_SUCCESSES:
            self.open_until = 0
            logger.info("Circuit breaker CLOSED (half-open probe succeeded)")


# ── Model Definitions ──────────────────────────────────

# Default model configurations
MODEL_REGISTRY: dict[str, ModelConfig] = {
    "gpt-4o": ModelConfig(
        name="gpt-4o",
        provider="openai",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        model_id="openai/gpt-4o",
        priority=1,
        cost_per_1k_input=0.005,
        cost_per_1k_output=0.015,
        max_tokens=8192,
    ),
    "claude-3.5-sonnet": ModelConfig(
        name="claude-3.5-sonnet",
        provider="anthropic",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        model_id="anthropic/claude-3.5-sonnet",
        priority=2,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        max_tokens=8192,
    ),
    "gemini-1.5-pro": ModelConfig(
        name="gemini-1.5-pro",
        provider="google",
        api_key_env="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model_id="gemini-1.5-pro",
        priority=3,
        cost_per_1k_input=0.00125,
        cost_per_1k_output=0.005,
        max_tokens=8192,
    ),
    "deepseek-chat": ModelConfig(
        name="deepseek-chat",
        provider="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        model_id="deepseek-chat",
        priority=4,
        cost_per_1k_input=0.00027,
        cost_per_1k_output=0.00110,
        max_tokens=8192,
    ),
}

# Task-to-model routing: task_type -> [ordered model names]
TASK_ROUTING: dict[TaskType, list[str]] = {
    TaskType.PITCH: [
        "claude-3.5-sonnet",     # Primary: Claude (best narrative quality)
        "gpt-4o",                # Fallback 1: GPT-4o
        "deepseek-chat",         # Fallback 2: DeepSeek Flash
        "gemini-1.5-pro",        # Fallback 3: Gemini
    ],
    TaskType.PRICING: [
        "gpt-4o",                # Primary: GPT-4o (best structured data)
        "claude-3.5-sonnet",     # Fallback 1: Claude
        "deepseek-chat",         # Fallback 2: DeepSeek
        "gemini-1.5-pro",        # Fallback 3: Gemini
    ],
    TaskType.PLANNING: [
        "deepseek-chat",         # Primary: DeepSeek (long context, code-savvy)
        "claude-3.5-sonnet",     # Fallback 1: Claude
        "gpt-4o",                # Fallback 2: GPT-4o
        "gemini-1.5-pro",        # Fallback 3
    ],
    TaskType.CODE: [
        "deepseek-chat",         # Primary: DeepSeek Flash (cheap + fast)
        "claude-3.5-sonnet",
        "gpt-4o",
        "gemini-1.5-pro",
    ],
    TaskType.RESEARCH: [
        "deepseek-chat",         # Primary: DeepSeek (long context, cheap)
        "gpt-4o",
        "claude-3.5-sonnet",
        "gemini-1.5-pro",
    ],
    TaskType.JSON: [
        "gpt-4o",                # Primary: GPT-4o (best structured output)
        "deepseek-chat",
        "claude-3.5-sonnet",
        "gemini-1.5-pro",
    ],
    TaskType.CHAT: [
        "deepseek-chat",         # Primary: DeepSeek Flash (cheap, fast)
        "gpt-4o",
        "claude-3.5-sonnet",
        "gemini-1.5-pro",
    ],
}


# ── LLM Router ─────────────────────────────────────────

class LLMRouterError(Exception):
    """Raised when all models have failed."""
    pass


class LLMRouter:
    """Multi-model LLM router with circuit breaker and automatic fallback.

    Features:
    - Priority-based model selection per task type
    - Circuit breaker per model (5 failures/60s → skip 300s)
    - Automatic fallback chain
    - Latency, token, and cost logging
    - Graceful degradation
    """

    def __init__(self):
        self._registry: dict[str, ModelConfig] = dict(MODEL_REGISTRY)
        self._circuits: dict[str, CircuitBreaker] = defaultdict(CircuitBreaker)
        self._routing: dict[TaskType, list[str]] = {
            k: list(v) for k, v in TASK_ROUTING.items()
        }
        self._client: Optional[httpx.AsyncClient] = None
        self._last_used_model: Optional[str] = None
        self._last_used_provider: Optional[str] = None

    def register_model(self, config: ModelConfig):
        """Register or update a model configuration."""
        self._registry[config.name] = config
        if config.name not in self._circuits:
            self._circuits[config.name] = CircuitBreaker()

    # ── Public API ──────────────────────────────────────

    async def chat(
        self,
        prompt: str,
        *,
        task_type: TaskType | str = TaskType.CHAT,
        system: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 180,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> str:
        """Send a chat completion through the best available model.

        Args:
            prompt: User prompt.
            task_type: Task category for model routing.
            system: Optional system prompt.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.
            timeout: Request timeout in seconds.
            user_id: Optional user ID for cost tracking.
            project_id: Optional project ID for cost tracking.

        Returns:
            Response text from the first successful model.

        Raises:
            LLMRouterError: If all models fail.
        """
        if isinstance(task_type, str):
            try:
                task_type = TaskType(task_type)
            except ValueError:
                task_type = TaskType.CHAT

        model_chain = self._routing.get(task_type, self._routing[TaskType.CHAT])
        errors = []

        for model_name in model_chain:
            config = self._registry.get(model_name)
            if not config:
                continue

            # Check circuit breaker
            circuit = self._circuits[model_name]
            if circuit.is_open:
                logger.debug(f"Skipping {model_name} (circuit open)")
                continue

            try:
                result, latency_ms, usage_data = await self._call_model(
                    config=config,
                    prompt=prompt,
                    system=system,
                    temperature=temperature or config.default_temperature,
                    max_tokens=max_tokens or config.max_tokens,
                    timeout=timeout,
                )

                # Record success
                circuit.record_success(latency_ms)
                self._last_used_model = model_name
                self._last_used_provider = config.provider

                # Track cost (pass usage_data directly — no data race)
                await self._track_cost(
                    config=config,
                    prompt=prompt,
                    response=result,
                    usage_data=usage_data,
                    latency_ms=latency_ms,
                    user_id=user_id,
                    project_id=project_id,
                    task_type=task_type.value,
                )

                logger.info(
                    f"LLM Router: {model_name} ({config.provider}) "
                    f"responded in {latency_ms:.0f}ms "
                    f"[task={task_type.value}]"
                )
                return result

            except Exception as e:
                circuit.record_failure()
                errors.append(f"{model_name}: {e}")
                logger.warning(
                    f"LLM Router fallback: {model_name} failed: {e}"
                )
                continue

        # All models failed
        raise LLMRouterError(
            f"All models failed for task_type={task_type.value}. "
            f"Errors: {'; '.join(errors)}"
        )

    async def json(
        self,
        prompt: str,
        *,
        task_type: TaskType | str = TaskType.JSON,
        system: str = "You are a precise JSON generator. Output ONLY valid JSON, no markdown, no explanation.",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: int = 180,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Get a JSON response through the best available model."""
        result = await self.chat(
            prompt=prompt,
            task_type=task_type,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            user_id=user_id,
            project_id=project_id,
        )
        return self._extract_json(result)

    @property
    def last_used_model(self) -> Optional[str]:
        """Get the last successfully used model name."""
        return self._last_used_model

    def get_status(self) -> dict:
        """Get current router status with circuit breaker states."""
        models = {}
        for name, config in self._registry.items():
            circuit = self._circuits[name]
            api_key = os.getenv(config.api_key_env, "")
            models[name] = {
                "provider": config.provider,
                "priority": config.priority,
                "available": bool(api_key),
                "circuit_open": circuit.is_open,
                "total_calls": circuit.total_calls,
                "total_failures": circuit.total_failures,
                "avg_latency_ms": round(circuit.total_latency_ms / max(circuit.total_calls, 1), 1),
                "consecutive_successes": circuit.consecutive_successes,
                "failure_count": circuit.failure_count,
            }

        return {
            "router": "LLMRouter v1",
            "status": "healthy",
            "last_used_model": self._last_used_model,
            "last_used_provider": self._last_used_provider,
            "models": models,
            "task_routing": {
                k.value: v for k, v in self._routing.items()
            },
        }

    # ── Model Call ──────────────────────────────────────

    async def _call_model(
        self,
        config: ModelConfig,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: int = 180,
    ) -> tuple[str, float, Optional[dict]]:
        """Call a specific model and return (response_text, latency_ms, usage).

        Returns usage dict for cost tracking (avoids data race).
        """
        start = time.monotonic()
        client = await self._get_client()
        api_key = await self._resolve_api_key(config)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": config.model_id or config.name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Google Gemini uses a different API format
        if config.provider == "google":
            return await self._call_gemini(config, prompt, system, temperature, max_tokens, timeout)

        # OpenRouter needs additional headers
        if "openrouter" in config.base_url:
            headers["Referer"] = "https://pitch-forge.com"
            headers["X-Title"] = "PitchForge"

        response = await client.post(
            f"{config.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=15.0),
        )

        if response.status_code == 429:
            raise RuntimeError(f"Rate limited by {config.provider}")
        if response.status_code >= 500:
            raise RuntimeError(f"{config.provider} server error: {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(
                f"{config.provider} API error {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"{config.provider} returned empty choices")

        content = choices[0].get("message", {}).get("content", "")
        latency_ms = (time.monotonic() - start) * 1000

        # Return usage data for cost tracking (avoids data race on instance state)
        usage = data.get("usage", {})
        usage_data = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        } if usage else None

        return content.strip(), latency_ms, usage_data

    async def _call_gemini(
        self,
        config: ModelConfig,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: int = 180,
    ) -> tuple[str, float, None]:
        """Call Google Gemini API (different endpoint format).

        Returns (text, latency_ms, None) — Gemini doesn't expose token
        counts in non-streaming, so usage_data is always None.
        """
        start = time.monotonic()
        client = await self._get_client()
        api_key = await self._resolve_api_key(config)

        contents = []
        if system:
            contents.append({
                "role": "user",
                "parts": [{"text": f"[System instruction: {system}]\n\n{prompt}"}]
            })
        else:
            contents.append({
                "role": "user",
                "parts": [{"text": prompt}]
            })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }

        url = (
            f"{config.base_url}/models/{config.model_id}:generateContent"
            f"?key={api_key}"
        )

        response = await client.post(
            url,
            json=payload,
            timeout=httpx.Timeout(timeout, connect=15.0),
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Gemini API error {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned empty candidates")

        text = ""
        for part in candidates[0].get("content", {}).get("parts", []):
            text += part.get("text", "")

        latency_ms = (time.monotonic() - start) * 1000

        # Gemini doesn't return token counts in non-streaming mode
        return text.strip(), latency_ms, None

    # ── Helpers ─────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(180, connect=15.0),
            )
        return self._client

    async def _resolve_api_key(self, config: ModelConfig) -> str:
        """Resolve API key from environment."""
        api_key = os.getenv(config.api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"{config.api_key_env} not set — {config.provider} unavailable"
            )
        return api_key

    async def _track_cost(
        self,
        config: ModelConfig,
        prompt: str,
        response: str,
        usage_data: Optional[dict],
        latency_ms: float,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        task_type: str = "chat",
    ):
        """Track LLM cost via cost_tracker.

        Args:
            usage_data: Token usage returned by _call_model or None.
        """
        try:
            if usage_data:
                prompt_tokens = usage_data.get("prompt_tokens", 0)
                completion_tokens = usage_data.get("completion_tokens", 0)
            else:
                # Estimate tokens from text if no usage data (Gemini, etc.)
                prompt_tokens = len(prompt) // 4
                completion_tokens = len(response) // 4

            cost_usd = round(
                (prompt_tokens / 1000) * config.cost_per_1k_input +
                (completion_tokens / 1000) * config.cost_per_1k_output,
                6,
            )

            await cost_tracker.record(
                provider=config.provider,
                model=config.name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                user_id=user_id,
                project_id=project_id,
                metadata={
                    "task_type": task_type,
                    "latency_ms": round(latency_ms, 1),
                    "router": "llm_router",
                },
            )
        except Exception as e:
            logger.debug(f"Cost tracking skipped (non-fatal): {e}")

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extract JSON from LLM response (handles markdown fences)."""
        if not text:
            return None

        start = text.find("```json")
        if start >= 0:
            start += 7
            end = text.find("```", start)
            if end >= 0:
                text = text[start:end].strip()

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            cleaned = text.replace("\n", " ").replace("\r", "")
            cleaned = cleaned.replace(", }", " }").replace(", ]", " ]")
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from: {text[:200]}...")
                return None


# ── Singleton ───────────────────────────────────────────

_router_instance: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    """Get or create the LLMRouter singleton."""
    global _router_instance
    if _router_instance is None:
        _router_instance = LLMRouter()
    return _router_instance


# Shortcut for imports
llm_router = get_router()
