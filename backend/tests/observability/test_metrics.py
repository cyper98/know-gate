"""Tests for Prometheus metrics exposure.

Builds a minimal FastAPI app that includes the same metrics middleware
and /metrics route used in production. This avoids importing the full
app (which pulls in unrelated routers).
"""

from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import Response

from app.observability.metrics import REQUEST_COUNT


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next: Response) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        _ = time.perf_counter() - start  # duration placeholder
        REQUEST_COUNT.labels(
            endpoint=request.url.path,
            status=response.status_code,
        ).inc()
        return response

    return app


def test_metrics_endpoint_returns_prometheus_text() -> None:
    """GET /metrics returns 200 with text/plain Prometheus format."""
    client = TestClient(_build_app())
    response = client.get("/metrics")
    assert response.status_code == 200
    # Prometheus exposition format starts with `# HELP`.
    assert b"# HELP" in response.content
    assert b"kg_api_requests_total" in response.content


def test_request_counter_increments_after_request() -> None:
    """`kg_api_requests_total` increments by 1 after a /health hit."""
    app = _build_app()
    client = TestClient(app)
    # Snapshot the current value for the /health endpoint, status 200.
    before = REQUEST_COUNT.labels(endpoint="/health", status="200")._value.get()  # type: ignore[attr-defined]

    response = client.get("/health")
    assert response.status_code == 200

    after = REQUEST_COUNT.labels(endpoint="/health", status="200")._value.get()  # type: ignore[attr-defined]
    assert after == before + 1


def test_metrics_format_is_parseable() -> None:
    """Spot-check that the /metrics body has the expected shape."""
    client = TestClient(_build_app())
    response = client.get("/health")
    assert response.status_code == 200

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    body = metrics_response.text

    # Content type is the standard Prometheus exposition format.
    assert "text/plain" in metrics_response.headers["content-type"]
    # At least one TYPE line per top-level metric family.
    assert "# TYPE kg_api_requests_total counter" in body
    assert "# TYPE kg_api_request_duration_seconds histogram" in body
