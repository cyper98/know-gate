"""Unit tests for the audit log writer (log_event) and decorator (@audited)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_log_event_calls_session_factory_and_inserts_row() -> None:
    """Happy path: log_event opens a session, executes a pg INSERT, commits."""
    from app.audit.log import log_event

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with patch("app.audit.log.get_session_factory", return_value=mock_factory):
        await log_event(
            actor_id="u-1",
            actor_email="alice@example.com",
            action="user.create",
            target_type="user",
            target_id="u-1",
            after={"email": "alice@example.com"},
            ip_address="127.0.0.1",
        )

    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_event_swallows_db_error_without_raising() -> None:
    """Best-effort: a DB write failure must NOT raise (audit is non-blocking)."""
    from app.audit.log import log_event

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute.side_effect = RuntimeError("DB down")

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with patch("app.audit.log.get_session_factory", return_value=mock_factory):
        # MUST NOT raise
        await log_event(
            actor_id="u-1",
            actor_email=None,
            action="user.create",
            target_type="user",
            target_id="u-1",
        )


@pytest.mark.asyncio
async def test_audited_decorator_captures_actor_from_kwargs_and_calls_log_event() -> None:
    """`@audited("user.create", "user")` on a service method: after the wrapped
    function returns, log_event is called with the actor from kwargs and the
    return value as `after`."""
    from app.audit.log import audited

    @audited("user.create", "user", capture_after=True)
    async def create_user(actor: dict, **kwargs):
        return {"id": "u-new", "email": "new@example.com", "actor_seen": actor}

    with patch("app.audit.log.log_event", new=AsyncMock()) as mock_log:
        result = await create_user(actor={"id": "u-actor", "email": "actor@example.com"})

    assert result["id"] == "u-new"
    # log_event was scheduled as a background task — let the loop run
    await asyncio.sleep(0)
    mock_log.assert_called_once()
    kwargs = mock_log.call_args.kwargs
    assert kwargs["action"] == "user.create"
    assert kwargs["target_type"] == "user"
    assert kwargs["target_id"] == "u-new"
    assert kwargs["actor_id"] == "u-actor"
    assert kwargs["after"]["email"] == "new@example.com"
