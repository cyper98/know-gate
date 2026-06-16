"""KnowGate FastAPI application entry point."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import Response

from app.api.errors import to_error_response
from app.api.middleware import RateLimitMiddleware
from app.api.v1 import auth as auth_router
from app.api.v1 import documents as documents_router
from app.api.v1 import feedback as feedback_router
from app.api.v1 import groups as groups_router
from app.api.v1 import query as query_router
from app.api.v1 import roles as roles_router
from app.api.v1 import settings as settings_router
from app.api.v1 import sources as sources_router
from app.api.v1 import sync_jobs as sync_jobs_router
from app.api.v1 import users as users_router
from app.api.v1 import webhooks as webhooks_router
from app.audit.middleware import ClientIPMiddleware
from app.cache.client import check_redis, close_redis
from app.config import get_settings
from app.db.init import check_connection
from app.logging import configure_logging, get_logger
from app.middleware.trace_id import TraceIdMiddleware
from app.observability.metrics import REQUEST_COUNT, REQUEST_DURATION
from app.observability.tracing import instrument_fastapi_app, setup_tracing
from app.storage.client import check_minio
from app.vector.client import check_qdrant, close_qdrant

settings = get_settings()
configure_logging(
    log_level=settings.kg_log_level,
    json_output=settings.is_production,
)
logger = get_logger(__name__)

# CORS allowed origins (tighten per OAuth callback)
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    f"http://{settings.kg_domain}:3000",
]

# Health check timeout (per backend, per check)
HEALTH_CHECK_TIMEOUT_SECONDS = 2.0

OPENAPI_TAGS = [
    {"name": "auth", "description": "Sign-in, sign-up, OAuth, magic links, token refresh."},
    {"name": "query", "description": "Ask a question and get an answer with citations."},
    {"name": "feedback", "description": "Rate past query answers (good/bad/source_missing)."},
    {"name": "documents", "description": "List + manage indexed documents."},
    {"name": "sources", "description": "Manage data source connections (Drive, Notion, ...)."},
    {"name": "sync-jobs", "description": "Inspect and retry background sync jobs."},
    {"name": "users", "description": "User management (admin only)."},
    {"name": "roles", "description": "Role and permission management (admin only)."},
    {"name": "groups", "description": "Access-group management (admin only)."},
    {"name": "settings", "description": "Instance settings + audit log (admin only)."},
    {"name": "webhooks", "description": "External push-notification receivers (e.g., Drive)."},
    {"name": "health", "description": "Liveness, readiness, Prometheus metrics."},
    {"name": "meta", "description": "API metadata."},
]


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
    description=(
        "Open-source RAG-based internal knowledge search & Q&A.\n\n"
        "All `/api/v1/*` endpoints return JSON. Success responses are the "
        "endpoint's Pydantic model directly; error responses follow the "
        "envelope `{ error: { code, message, details? } }`."
    ),
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
    # Security schemes for the OpenAPI spec
    components={
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT access token (RS256). 15-min TTL.",
            },
        }
    },
)

# === Tracing setup (OTel TracerProvider + instrumentations) ===
# Must run before the app starts receiving traffic.
setup_tracing()
instrument_fastapi_app(app)

# === Middleware (outermost added last) ===
# Trace-id binding (binds trace_id to structlog contextvars, adds
# X-Trace-Id response header). Outermost so every downstream
# middleware/handler sees the bound context.
app.add_middleware(TraceIdMiddleware)
# Global IP rate limit
app.add_middleware(RateLimitMiddleware)
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


# === Global error handlers ===
# Re-shape HTTPException + RequestValidationError + unhandled into the
# standard error envelope. Keeps endpoint code focused on business logic.
@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    status_code, body = to_error_response(exc)
    return JSONResponse(status_code=status_code, content=body.model_dump())


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    # FastAPI registers its own HTTPException handler above; this catches
    # anything else (DB errors, KeyError, RuntimeError, ...). The bare
    # HTTPException here is a re-import to keep the check local.
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        status_code, body = to_error_response(exc)
        headers = getattr(exc, "headers", None)
        return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)
    status_code, body = to_error_response(exc)
    return JSONResponse(status_code=status_code, content=body.model_dump())


# === Register API routers ===
# Order matters only for OpenAPI tag order in the docs UI. Auth first.
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(query_router.router, prefix="/api/v1")
app.include_router(feedback_router.router, prefix="/api/v1")
app.include_router(documents_router.router, prefix="/api/v1")
app.include_router(sources_router.router, prefix="/api/v1")
app.include_router(sync_jobs_router.router, prefix="/api/v1")
app.include_router(users_router.router, prefix="/api/v1")
app.include_router(roles_router.router, prefix="/api/v1")
app.include_router(groups_router.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")
app.include_router(webhooks_router.router, prefix="/api/v1")


@app.middleware("http")
async def metrics_middleware(request: Request, call_next: Response) -> Response:
    """Record request count + duration metrics."""
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    endpoint = request.url.path
    REQUEST_COUNT.labels(
        endpoint=endpoint,
        status=response.status_code,
    ).inc()
    REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)
    return response


async def _check_with_timeout(coro, name: str) -> dict[str, str]:
    """Run a health check with timeout. Returns {name, status, error?}.

    all check timeouts 2s.
    """
    try:
        ok = await asyncio.wait_for(coro, timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        return {"name": name, "status": "ok" if ok else "fail"}
    except TimeoutError:
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
