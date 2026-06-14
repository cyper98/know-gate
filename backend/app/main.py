"""KnowGate FastAPI application entry point."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(
    log_level=settings.kg_log_level,
    json_output=settings.is_production,
)
logger = get_logger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "kg_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status"],
)
REQUEST_DURATION = Histogram(
    "kg_api_request_duration_seconds",
    "API request duration",
    ["method", "endpoint"],
)

# CORS allowed origins (Phase 03: tighten per OAuth callback)
CORS_ALLOWED_ORIGINS = [
    f"http://localhost:3000",
    f"http://{settings.kg_domain}:3000",
]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - startup/shutdown hooks."""
    logger.info(
        "knowgate_starting",
        env=settings.kg_env,
        domain=settings.kg_domain,
        version="0.1.0",
    )
    yield
    logger.info("knowgate_shutdown")


app = FastAPI(
    title="KnowGate API",
    description="Open-source RAG-based internal knowledge search & Q&A",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)

# CORS (web origin only by default)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next: Response) -> Response:
    """Record request count + duration metrics."""
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    endpoint = request.url.path
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status=response.status_code,
    ).inc()
    REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(duration)
    return response


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe - process is up."""
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready() -> JSONResponse:
    """Readiness probe - dependencies (DB, Redis, Qdrant, MinIO) are reachable.

    Full implementation in Phase 02 (Data Layer). Returns 200 if process up.
    """
    # TODO Phase 02: check postgres, redis, qdrant, minio
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "checks": {"process": "ok"}},
    )


@app.get("/metrics", tags=["health"])
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1", tags=["meta"])
async def api_root() -> dict[str, str]:
    """API root - info."""
    return {
        "name": "KnowGate API",
        "version": "0.1.0",
        "docs": "/api/v1/docs",
    }
