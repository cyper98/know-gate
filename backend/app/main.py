"""KnowGate FastAPI application entry point."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1 import auth as auth_router
from app.api.v1 import feedback as feedback_router
from app.api.v1 import query as query_router
from app.api.v1 import sources as sources_router
from app.api.v1 import webhooks as webhooks_router
from app.audit.middleware import ClientIPMiddleware
from app.cache.client import check_redis, close_redis
from app.config import get_settings
from app.db.init import check_connection
from app.logging import configure_logging, get_logger
from app.storage.client import check_minio
from app.vector.client import check_qdrant, close_qdrant

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

# CORS allowed origins (tighten per OAuth callback)
CORS_ALLOWED_ORIGINS = [
    f"http://localhost:3000",
    f"http://{settings.kg_domain}:3000",
]

# Health check timeout (per backend, per check)
HEALTH_CHECK_TIMEOUT_SECONDS = 2.0


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan - startup/shutdown hooks.

    On startup: log info (per-backend init is handled by docker-compose init
    container or dev `make up` workflow).
    On shutdown: close Redis + Qdrant clients gracefully.
    """
    logger.info(
        "knowgate_starting",
        env=settings.kg_env,
        domain=settings.kg_domain,
        version="0.1.0",
    )
    yield
    logger.info("knowgate_shutdown")
    # Graceful close
    await close_redis()
    await close_qdrant()


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
# Client IP capture (for audit + rate limit). Must come after CORS so
# X-Forwarded-For is parsed correctly when behind a proxy.
app.add_middleware(ClientIPMiddleware)

# Register API routers
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(sources_router.router, prefix="/api/v1")
app.include_router(webhooks_router.router, prefix="/api/v1")
app.include_router(query_router.router, prefix="/api/v1")
app.include_router(feedback_router.router, prefix="/api/v1")


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


async def _check_with_timeout(coro, name: str) -> dict[str, str]:
    """Run a health check with timeout. Returns {name, status, error?}.

    all check timeouts 2s.
    """
    try:
        ok = await asyncio.wait_for(coro, timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        return {"name": name, "status": "ok" if ok else "fail"}
    except asyncio.TimeoutError:
        return {"name": name, "status": "fail", "error": "timeout"}
    except Exception as e:
        return {"name": name, "status": "fail", "error": str(e)[:200]}


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness probe - process is up.

    Does NOT check dependencies (use /ready for that). K8s uses this for
    'is the process alive?' — should always return 200 if the app started.
    """
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
async def ready() -> JSONResponse:
    """Readiness probe - all 4 backends (PG, Qdrant, Redis, MinIO) reachable.

    200 if all healthy, 503 if any fail.
    Each check has 2s timeout. Checks run in parallel.
    """
    checks = await asyncio.gather(
        _check_with_timeout(check_connection(), "postgres"),
        _check_with_timeout(check_qdrant(), "qdrant"),
        _check_with_timeout(check_redis(), "redis"),
        _check_with_timeout(check_minio(), "minio"),
    )
    all_ok = all(c["status"] == "ok" for c in checks)
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "ready" if all_ok else "degraded",
            "checks": {c["name"]: c for c in checks},
        },
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
