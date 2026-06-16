"""Trace-ID middleware.

- Reads `traceparent` (W3C trace context) from the incoming request
  when present; otherwise generates a fresh 32-char hex trace_id.
- Binds the trace_id to structlog contextvars so every log line in
  the request scope carries it automatically.
- Adds `X-Trace-Id` to the response headers for client correlation.
"""

from __future__ import annotations

import secrets
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# W3C traceparent: 00-<trace-id 32 hex>-<span-id 16 hex>-<flags 2 hex>
_TRACEPARENT_VERSION = "00"


def _parse_traceparent(header: str) -> str | None:
    """Extract trace_id from a W3C traceparent header. Returns None if invalid."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    version, trace_id, _span_id, _flags = parts
    if version != _TRACEPARENT_VERSION:
        return None
    if len(trace_id) != 32 or not all(c in "0123456789abcdef" for c in trace_id.lower()):
        return None
    return trace_id


def _new_trace_id() -> str:
    """Generate a fresh 32-char lowercase hex trace id."""
    return uuid.uuid4().hex


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Starlette middleware: bind trace_id to logs and response header."""

    HEADER_NAME = "X-Trace-Id"

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("traceparent")
        trace_id = _parse_traceparent(incoming) if incoming else None
        if trace_id is None:
            trace_id = _new_trace_id()

        # Bind to structlog contextvars — every log() inside the
        # request scope will include trace_id automatically.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            request_id=secrets.token_hex(8),
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)
        response.headers[self.HEADER_NAME] = trace_id
        return response


__all__ = ["TraceIdMiddleware"]
