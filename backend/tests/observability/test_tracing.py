"""Tests for the trace-id middleware and OTel correlation."""

from __future__ import annotations

import re

import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging import _scrub_secrets, configure_logging, get_logger  # type: ignore[attr-defined]
from app.middleware.trace_id import TraceIdMiddleware, _parse_traceparent

_HEX_32 = re.compile(r"^[0-9a-f]{32}$")


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceIdMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/probe")
    async def probe() -> dict[str, str]:
        # Emit a log inside the request scope so the bound contextvars
        # are visible to the structlog processor chain.
        get_logger("probe").info("probe_event")
        return {"status": "ok"}

    return app


def test_response_has_x_trace_id_header() -> None:
    """Every HTTP response carries an X-Trace-Id header with 32 hex chars."""
    client = TestClient(_build_app())
    response = client.get("/health")
    assert response.status_code == 200
    trace_id = response.headers.get("X-Trace-Id")
    assert trace_id is not None
    assert _HEX_32.match(trace_id), f"trace id must be 32 hex chars, got: {trace_id!r}"


def test_existing_traceparent_is_respected() -> None:
    """A valid W3C traceparent on the request is echoed back as X-Trace-Id."""
    client = TestClient(_build_app())
    incoming_trace = "0af7651916cd43dd8448eb211c80319c"
    response = client.get(
        "/health",
        headers={"traceparent": f"00-{incoming_trace}-00f067aa0ba902b7-01"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Trace-Id") == incoming_trace


def test_traceparent_parser_rejects_malformed() -> None:
    """Malformed traceparent values return None (caller falls back to gen)."""
    assert _parse_traceparent("") is None
    assert _parse_traceparent("garbage") is None
    assert _parse_traceparent("00-short-00f067aa0ba902b7-01") is None
    # Wrong version → None.
    assert _parse_traceparent("01-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01") is None


def test_trace_id_is_bound_to_structlog_context() -> None:
    """A log emitted inside the request scope carries the bound trace_id."""
    captured: dict[str, object] = {}

    def _capture(_logger, _method, event_dict):  # type: ignore[no-untyped-def]
        captured.clear()
        captured.update(event_dict)
        return event_dict

    configure_logging(log_level="INFO", json_output=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _capture,
            _scrub_secrets,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    client = TestClient(_build_app())
    response = client.get("/probe")
    assert response.status_code == 200
    response_trace = response.headers["X-Trace-Id"]

    # The probe route emitted a log inside the request scope; the
    # capture processor saw the bound contextvars.
    assert captured.get("trace_id") == response_trace
    assert captured.get("event") == "probe_event"

    # Restore default config so other tests aren't affected.
    configure_logging(log_level="INFO", json_output=True)
