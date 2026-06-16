"""OpenTelemetry tracing setup for KnowGate.

Installs a TracerProvider with OTLP/gRPC exporter, configures resource
attributes (service name, version, deployment environment), and wires
auto-instrumentation for FastAPI, SQLAlchemy, and httpx.

Environment variables:
- OTEL_SDK_DISABLED=true  → no-op setup (no exporter, no instrumentations)
- OTEL_EXPORTER_OTLP_ENDPOINT  → OTLP gRPC endpoint (default: localhost:4317)
- KG_ENV                  → sets deployment.environment (development|staging|production)

The function is idempotent: a second call returns the same provider.
"""

from __future__ import annotations

import os
import threading

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_setup_lock = threading.Lock()
_setup_done = False


def _build_resource() -> Resource:
    """Build the OTel Resource with service + deployment metadata."""
    settings = get_settings()
    attrs: dict[str, str] = {
        "service.name": os.getenv("OTEL_SERVICE_NAME", "knowgate-api"),
        "service.version": os.getenv("KG_SERVICE_VERSION", "0.1.0"),
        "deployment.environment": settings.kg_env,
    }
    return Resource.create(attrs)


def setup_tracing() -> TracerProvider | None:
    """Set up OpenTelemetry tracing.

    Returns the active TracerProvider, or None if disabled by
    `OTEL_SDK_DISABLED=true`. Safe to call multiple times.
    """
    global _setup_done

    if os.getenv("OTEL_SDK_DISABLED", "").lower() in ("true", "1", "yes"):
        logger.info("otel_disabled")
        return None

    with _setup_lock:
        if _setup_done:
            existing = trace.get_tracer_provider()
            return existing if isinstance(existing, TracerProvider) else None

        resource = _build_resource()
        provider = TracerProvider(resource=resource)

        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        # OTLP gRPC exporter derives ":<port>" from endpoint; OTel SDK
        # accepts the full URL form and extracts host:port itself.
        try:
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception as e:
            # Don't crash app startup on exporter misconfig — log and
            # continue with a no-op provider (in-process spans still work).
            logger.error("otel_exporter_init_failed", endpoint=endpoint, error=str(e)[:200])

        trace.set_tracer_provider(provider)
        _setup_done = True

        # === Auto-instrumentation ===
        # Import inside the function so the OTel deps are optional at
        # module-import time. Each instrumentor is idempotent.
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            # FastAPI app is passed at instrumentation time; we expose
            # a hook so main.py can finish wiring once the app exists.
            HTTPXClientInstrumentor().instrument()
            SQLAlchemyInstrumentor().instrument()
            logger.info("otel_instrumented_httpx_sqlalchemy")
        except Exception as e:
            logger.warning("otel_instrumentation_partial", error=str(e)[:200])

        logger.info("otel_tracing_setup", endpoint=endpoint)
        return provider


def instrument_fastapi_app(app) -> None:
    """Instrument an existing FastAPI app instance.

    Must be called after the app is created and routes are registered.
    Idempotent — second call is a no-op.
    """
    if os.getenv("OTEL_SDK_DISABLED", "").lower() in ("true", "1", "yes"):
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("otel_instrumented_fastapi")
    except Exception as e:
        logger.warning("otel_fastapi_instrument_failed", error=str(e)[:200])


__all__ = ["instrument_fastapi_app", "setup_tracing"]
