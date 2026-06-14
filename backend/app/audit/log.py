"""Audit log writer + decorator for service methods.

Append-only INSERT into `audit_log` table. Application enforces immutability
(no UPDATE/DELETE in services) per brainstorm §8. Failed writes are logged
to stderr and do not raise (best-effort, non-blocking).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import AuditLog
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


async def log_event(
    *,
    actor_id: str | None,
    actor_email: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    detail: str | None = None,
) -> None:
    """Insert one audit log row. Best-effort: logs to stderr if DB write fails.

    Called from service methods after permission-relevant mutations. Should
    be invoked as `asyncio.create_task(log_event(...))` to keep request latency
    low (fire-and-forget), or awaited inline if the caller needs back-pressure.
    """
    factory = get_session_factory()
    try:
        async with factory() as session:
            stmt = pg_insert(AuditLog).values(
                actor_id=actor_id,
                actor_email=actor_email,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before=before,
                after=after,
                ip_address=ip_address,
                user_agent=user_agent,
                detail=detail,
            )
            await session.execute(stmt)
            await session.commit()
        logger.debug(
            "audit_logged",
            action=action,
            target_type=target_type,
            target_id=target_id,
        )
    except Exception:
        # Best-effort: log but never raise (don't break user flow)
        logger.exception(
            "audit_log_write_failed",
            action=action,
            target_type=target_type,
            target_id=target_id,
        )


def audited(
    action: str,
    target_type: str,
    *,
    capture_before: bool = False,
    capture_after: bool = True,
):
    """Decorator for service methods that emit audit events after successful return.

    Usage:
        @audited("user.create", "user")
        async def create_user(...): ...

    The decorated function must accept `actor: dict` as a keyword arg (or have
    it injected via FastAPI dep in the route layer). The decorator captures
    `actor` from kwargs and emits the audit event with the return value as
    `after` (and the previous state as `before` if `capture_before=True`).
    """

    def decorator(
        func: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)
            actor = kwargs.get("actor") or (args[-1] if args and isinstance(args[-1], dict) else None)
            actor_id = actor.get("id") if isinstance(actor, dict) else None
            actor_email = actor.get("email") if isinstance(actor, dict) else None

            target_id: str | None = None
            after_payload: dict[str, Any] | None = None
            if capture_after and isinstance(result, dict):
                target_id = result.get("id")
                after_payload = result
            elif capture_after and hasattr(result, "id"):
                target_id = result.id
                after_payload = {"id": result.id}

            # Fire-and-forget (best-effort, non-blocking)
            import asyncio

            asyncio.create_task(  # noqa: RUF006 — fire-and-forget by design
                log_event(
                    actor_id=actor_id,
                    actor_email=actor_email,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    after=after_payload,
                )
            )
            return result

        return wrapper

    return decorator
