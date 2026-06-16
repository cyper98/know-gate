"""Rate-limit + request-size middleware.

Two layers:
1. **Per-endpoint token bucket** (in handlers via `Depends`) — already
   implemented for `/auth/login` and `/query` (Redis sliding window).
2. **Global IP throttle** (this middleware) — coarse 429 gate for any
   path, to catch bots / abuse before the heavy handlers run.

Why a global IP throttle:
- Defense in depth: if a new endpoint forgets to add a per-user limit,
  the IP throttle still caps total damage.
- Cheap: single Redis op per request (sliding window over IP+minute).

Limits are deliberately generous (e.g., 600 req/min/IP) so the middleware
only triggers for clear abuse, not normal client bursts. Per-endpoint
limits stay tight.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.responses import ErrorCode, ErrorDetail, ErrorResponse
from app.cache.helpers import check_ip_rate_limit
from app.config import get_settings

from app.logging import get_logger

logger = get_logger(__name__)


# Paths that bypass the global throttle (so health checks / metrics /
# the OAuth callback aren't constrained). These endpoints have their
# own per-endpoint limits or are infra.
_BYPASS_PATHS = frozenset(
    {
        "/health",
        "/ready",
        "/metrics",
        "/api/v1",  # API root (meta info)
        "/api/v1/openapi.json",
        "/api/v1/docs",
        "/api/v1/redoc",
        # Webhooks: provider-driven, can't be IP-throttled
        # (they sign their requests; per-source cooldown lives elsewhere).
        "/api/v1/webhooks/google-drive",
    }
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global IP-based sliding-window rate limit (600 req/min/IP default).

    Triggers a 429 with the standard error envelope. Adds `Retry-After`
    and `X-RateLimit-*` headers so well-behaved clients can back off.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in _BYPASS_PATHS:
            return await call_next(request)

        settings = get_settings()
        # Per-IP per-minute throttle
        client_ip = (
            getattr(request.state, "client_ip", None)
            or (request.client.host if request.client else None)
            or "unknown"
        )
        count, allowed = await check_ip_rate_limit(
            client_ip,
            window=60,
            limit=settings.rate_limit_global_per_minute,
        )
        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                ip=client_ip,
                path=path,
                count=count,
                limit=settings.rate_limit_global_per_minute,
            )
            return JSONResponse(
                status_code=429,
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(settings.rate_limit_global_per_minute),
                    "X-RateLimit-Remaining": "0",
                },
                content=ErrorResponse(
                    error=ErrorDetail(
                        code=ErrorCode.RATE_LIMITED,
                        message=(
                            f"Too many requests from this IP: {count} in the last 60s "
                            f"(limit {settings.rate_limit_global_per_minute}/min). "
                            "Slow down and try again shortly."
                        ),
                    )
                ).model_dump(),
            )

        response = await call_next(request)
        # Expose the remaining quota so clients can self-throttle
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_global_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, settings.rate_limit_global_per_minute - count)
        )
        return response


__all__ = ["RateLimitMiddleware"]
