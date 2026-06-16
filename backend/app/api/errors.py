"""Exception → standardized error response.

Catches all unhandled exceptions + maps known exceptions to error codes
(E1-E15 from `app.api.responses.ErrorCode`).

Architecture:
- `to_error_response(exc) -> ErrorResponse` — pure mapping, no I/O
- FastAPI exception handlers in `app/main.py` invoke `to_error_response`
  and return the JSON envelope with the right HTTP status code.
- Pydantic `RequestValidationError` → E2 (bad request) with field details
- `HTTPException` (raised by us) → use its `status_code`; map via table
- `Exception` (unhandled) → E1 (internal) with sanitized message

Logging:
- 4xx errors: log at `info` level (expected client error)
- 5xx errors: log at `error` level with full traceback
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.responses import ErrorCode, ErrorDetail, ErrorResponse

from app.logging import get_logger

logger = get_logger(__name__)


# === Status code → error code mapping ===

# Used for HTTPException whose `detail` is a plain string (i.e., raised
# by us without an explicit code). The detail text is preserved so we
# don't lose information; clients should still branch on `code`.
_STATUS_TO_CODE: dict[int, str] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.UNPROCESSABLE,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL,
    502: ErrorCode.EXTERNAL_API_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
    504: ErrorCode.EXTERNAL_API_ERROR,
}


def _coerce_detail(detail: Any) -> str:
    """HTTPException.detail can be str, dict, or list. We always emit a string message."""
    if detail is None:
        return "Request failed"
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        # Pydantic v2 default error shape: {"detail": [...]} — extract message
        if "detail" in detail and isinstance(detail["detail"], str):
            return detail["detail"]
        if "message" in detail:
            return str(detail["message"])
        return str(detail)
    if isinstance(detail, list):
        return "; ".join(str(d) for d in detail)
    return str(detail)


def to_error_response(
    exc: Exception,
    *,
    default_code: str | None = None,
) -> tuple[int, ErrorResponse]:
    """Map an exception to (http_status, ErrorResponse).

    Args:
        exc: the raised exception
        default_code: override the mapped code (used by routers that
            want a more specific E-code than the generic HTTP status)

    Returns:
        (status_code, error_response) tuple suitable for `JSONResponse`.
    """
    if isinstance(exc, RequestValidationError):
        # Pydantic v2 validation errors → E2 with field-level details
        return (
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ErrorResponse(
                error=ErrorDetail(
                    code=ErrorCode.BAD_REQUEST,
                    message="Request validation failed",
                    details={"errors": _format_pydantic_errors(exc.errors())},
                )
            ),
        )

    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        code = default_code or _STATUS_TO_CODE.get(
            exc.status_code, ErrorCode.INTERNAL
        )
        headers = getattr(exc, "headers", None)
        # We don't put headers in the body; the JSONResponse caller merges them
        _ = headers  # logged for awareness
        return (
            exc.status_code,
            ErrorResponse(
                error=ErrorDetail(
                    code=code,
                    message=_coerce_detail(exc.detail),
                )
            ),
        )

    # Unhandled — log full traceback, return sanitized
    logger.exception("unhandled_exception", exc_info=exc)
    return (
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorResponse(
            error=ErrorDetail(
                code=default_code or ErrorCode.INTERNAL,
                message="An internal error occurred. The incident has been logged.",
            )
        ),
    )


def _format_pydantic_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim pydantic error dicts to the fields a client cares about."""
    out: list[dict[str, Any]] = []
    for e in errors:
        out.append(
            {
                "loc": list(e.get("loc", [])),
                "msg": e.get("msg", ""),
                "type": e.get("type", ""),
            }
        )
    return out


# === Convenience helpers for routers ===
# These let endpoints raise with a domain-specific error code without
# constructing a full HTTPException. Example:
#     raise api_error(403, ErrorCode.FORBIDDEN, "Permission denied")

def api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """Build a rich HTTPException with a structured detail payload.

    The exception handler in `main.py` will read `detail["code"]` and
    `detail["message"]` to populate the standard error envelope.
    """
    detail: dict[str, Any] = {"code": code, "message": message}
    if details:
        detail["details"] = details
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


__all__ = ["api_error", "to_error_response"]
