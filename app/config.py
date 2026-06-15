"""App configuration — loads from environment with sensible defaults.

Enhanced with Stripe, rate limiting, multi-LLM fallback, and WebSocket support
from Startup Engine merge — June 2026.
"""

import base64
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Resolve .env relative to project root — works regardless of CWD
# config.py is at code/backend/app/ → 2 levels up = code/backend/ (where .env lives)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # Fallback for Docker (CWD = /app)


class Settings:
    # ── App ─────────────────────────────────────────────
    APP_NAME: str = "PitchForge"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production-pls")
    ALLOWED_ORIGINS: list[str] = os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:8086,http://localhost:3000"
    ).split(",")

    # ── Clerk (autenticación) ───────────────────────────
    CLERK_SECRET_KEY: Optional[str] = os.getenv("CLERK_SECRET_KEY")
    CLERK_PUBLISHABLE_KEY: Optional[str] = os.getenv("CLERK_PUBLISHABLE_KEY")
    CLERK_AUTHORIZED_PARTIES: list[str] = os.getenv(
        "CLERK_AUTHORIZED_PARTIES", "http://localhost:5173,http://localhost:5174,http://localhost:3000"
    ).split(",")

    # ── Auth (legacy fallback) ───────────────────────────
    API_KEY: Optional[str] = os.getenv("API_KEY")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")

    # ── MongoDB (reemplaza SQLite) ──────────────────────
    MONGODB_URL: Optional[str] = os.getenv("MONGODB_URL")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "pitch_forge")

    # ── Redis / Arq ─────────────────────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    # ── Rate Limiting (slowapi) ─────────────────────────
    RATE_LIMIT_VALIDATE: str = os.getenv("RATE_LIMIT_VALIDATE", "10/hour")
    RATE_LIMIT_GENERAL: str = os.getenv("RATE_LIMIT_GENERAL", "100/hour")

    # ── Stripe ──────────────────────────────────────────
    STRIPE_SECRET_KEY_B64: Optional[str] = os.getenv("STRIPE_SECRET_KEY_B64")
    STRIPE_SECRET_KEY: Optional[str] = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY: Optional[str] = os.getenv("STRIPE_PUBLISHABLE_KEY")
    STRIPE_WEBHOOK_SECRET: Optional[str] = os.getenv("STRIPE_WEBHOOK_SECRET")

    @property
    def STRIPE_API_KEY(self) -> Optional[str]:
        """Resolve the Stripe secret key (direct or base64)."""
        if self.STRIPE_SECRET_KEY:
            return self.STRIPE_SECRET_KEY
        if self.STRIPE_SECRET_KEY_B64:
            try:
                return base64.b64decode(self.STRIPE_SECRET_KEY_B64).decode("utf-8")
            except Exception:
                return None
        return None

    # Stripe Price IDs — set automatically by setup script
    PRICE_STARTER: Optional[str] = os.getenv("PRICE_STARTER")
    PRICE_PRO: Optional[str] = os.getenv("PRICE_PRO")
    PRICE_CODE_MVP: Optional[str] = os.getenv("PRICE_CODE_MVP")

    # Tier limits (can be overridden by Stripe product metadata)
    TIER_LIMITS: dict = {
        "free": {"max_tokens": 2000, "max_research_per_day": 1, "max_projects_per_month": 3},
        "starter": {"max_tokens": 10000, "max_research_per_day": 5, "max_projects_per_month": 15},
        "pro": {"max_tokens": 50000, "max_research_per_day": 20, "max_projects_per_month": 50},
        "code_mvp": {"max_tokens": 100000, "max_research_per_day": 50, "max_projects_per_month": 100},
    }

    # ── LLM Integration ─────────────────────────────────
    HERMES_LLM: bool = os.getenv("HERMES_LLM", "true").lower() == "true"
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    PERPLEXITY_API_KEY: Optional[str] = os.getenv("PERPLEXITY_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    NVIDIA_API_KEY: Optional[str] = os.getenv("NVIDIA_API_KEY")

    # ── Logging ─────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Sentry (error tracking) — TASK-023 ──────────────
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN")
    SENTRY_ENVIRONMENT: str = os.getenv("SENTRY_ENVIRONMENT", "development")
    SENTRY_RELEASE: Optional[str] = os.getenv("SENTRY_RELEASE")

    # ── OpenTelemetry / APM — TASK-024 ──────────────────
    OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "true").lower() in ("true", "1", "yes")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    OTEL_EXPORTER_OTLP_HEADERS: Optional[str] = os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
    OTEL_EXPORTER_OTLP_PROTOCOL: str = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "pitchforge-api")

    # ── LLM Cost Monitoring — TASK-026 ───────────────────
    # Slack webhook URL for budget alert notifications
    SLACK_WEBHOOK_URL: Optional[str] = os.getenv("SLACK_WEBHOOK_URL")
    # Daily total budget alert threshold in USD
    LLM_COST_DAILY_BUDGET_USD: float = float(os.getenv("LLM_COST_DAILY_BUDGET_USD", "100.0"))
    # Per-user daily budget alert threshold in USD
    LLM_COST_USER_DAILY_BUDGET_USD: float = float(os.getenv("LLM_COST_USER_DAILY_BUDGET_USD", "10.0"))


settings = Settings()
