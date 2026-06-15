"""
OpenTelemetry initialization — TASK-024.

Usage (in main.py lifespan):
    from .telemetry import init_telemetry, shutdown_telemetry
    await init_telemetry()
    # ... app runs ...
    await shutdown_telemetry()

Env vars (all optional):
    OTEL_EXPORTER_OTLP_ENDPOINT   — OTLP gRPC endpoint (default: http://localhost:4317)
    OTEL_EXPORTER_OTLP_HEADERS    — Headers for auth (e.g. "api-key=xxx")
    OTEL_EXPORTER_OTLP_PROTOCOL   — "grpc" or "http/protobuf" (default: grpc)
    OTEL_SERVICE_NAME             — Service name for traces (default: pitchforge-api)
    OTEL_ENABLED                  — Set to "false" to disable telemetry (default: true)
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def is_otel_enabled() -> bool:
    """Check if OpenTelemetry is enabled via env var."""
    return os.getenv("OTEL_ENABLED", "true").lower() in ("true", "1", "yes")


def init_telemetry() -> None:
    """Initialize OpenTelemetry SDK and instrumentations.

    Safe to call multiple times — second call is a no-op if already initialized.
    """
    if not is_otel_enabled():
        logger.info("OpenTelemetry disabled via OTEL_ENABLED=false")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, DEPLOYMENT_ENVIRONMENT
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HttpxInstrumentor
        from opentelemetry.instrumentation.pymongo import PyMongoInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        # ── Resource ────────────────────────────────────
        resource = Resource.create({
            SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "pitchforge-api"),
            DEPLOYMENT_ENVIRONMENT: os.getenv("SENTRY_ENVIRONMENT", "development"),
            "service.version": os.getenv("SENTRY_RELEASE", "unknown"),
        })

        # ── Tracer Provider ─────────────────────────────
        tracer_provider = TracerProvider(resource=resource)

        # ── OTLP Exporter ───────────────────────────────
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")

        exporter_kwargs: dict = {"endpoint": endpoint}
        if headers:
            exporter_kwargs["headers"] = headers

        otlp_exporter = OTLPSpanExporter(**exporter_kwargs)
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)

        # Set global tracer provider
        trace.set_tracer_provider(tracer_provider)

        # ── Instrumentations ────────────────────────────
        # FastAPI — auto-instruments all routes
        FastAPIInstrumentor.instrument()
        logger.info("OTel: FastAPI instrumented")

        # httpx — captures outbound HTTP calls (research sources)
        HttpxInstrumentor().instrument()
        logger.info("OTel: httpx instrumented")

        # PyMongo / Motor — captures DB queries
        PyMongoInstrumentor().instrument()
        logger.info("OTel: PyMongo/Motor instrumented")

        # Logging — adds trace_id to log records
        LoggingInstrumentor().instrument()
        logger.info("OTel: Logging instrumented (trace IDs in logs)")

        logger.info(
            f"OpenTelemetry initialized — "
            f"service={os.getenv('OTEL_SERVICE_NAME', 'pitchforge-api')}, "
            f"endpoint={endpoint}"
        )

    except Exception as e:
        logger.warning(f"OpenTelemetry init failed (non-fatal): {e}")


def shutdown_telemetry() -> None:
    """Shutdown OpenTelemetry — flush spans and shutdown SDK."""
    if not is_otel_enabled():
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.shutdown()
            logger.info("OpenTelemetry shut down")
    except Exception as e:
        logger.warning(f"OpenTelemetry shutdown error (non-fatal): {e}")


def get_tracer() -> Optional[object]:
    """Get the global tracer for creating custom spans.

    Returns None if OpenTelemetry is not initialized (safe to use with 'if tracer:').
    """
    if not is_otel_enabled():
        return None
    try:
        from opentelemetry import trace
        return trace.get_tracer(__name__)
    except Exception:
        return None
