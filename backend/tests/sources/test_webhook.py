"""Unit tests for the webhook handlers (Drive only for MVP)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _webhook_headers(
    *,
    channel_id: str = "channel-1",
    channel_token: str | None = "src-1",
    resource_id: str = "resource-1",
    resource_state: str = "update",
    message_number: str = "2",
) -> dict[str, str]:
    h = {
        "X-Goog-Channel-Id": channel_id,
        "X-Goog-Resource-Id": resource_id,
        "X-Goog-Resource-State": resource_state,
        "X-Goog-Message-Number": message_number,
    }
    if channel_token is not None:
        h["X-Goog-Channel-Token"] = channel_token
    return h


def test_webhook_missing_channel_token_returns_400(client: TestClient) -> None:
    """No token → 400 (the request isn't for us)."""
    resp = client.post(
        "/api/v1/webhooks/google-drive",
        headers=_webhook_headers(channel_token=None),
    )
    assert resp.status_code == 400


def test_webhook_sync_ping_is_acknowledged_without_enqueueing(client: TestClient) -> None:
    """`X-Goog-Resource-State: sync` is the initial channel-creation ping —
    we should ACK fast and NOT enqueue a sync task."""
    with patch("app.tasks.sync.sync_source_task") as mock_task:
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/webhooks/google-drive",
            headers=_webhook_headers(resource_state="sync"),
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["received"] == "sync"
    mock_task.delay.assert_not_called()


def test_webhook_unknown_channel_acks_with_warning(client: TestClient) -> None:
    """Channel ID not in DB → ACK (so Drive doesn't retry) but don't enqueue."""
    with patch("app.tasks.sync.sync_source_task") as mock_task:
        mock_task.delay = MagicMock()
        with patch("app.api.v1.webhooks.get_session_factory") as mock_factory:
            # Session returns no source (None)
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
            mock_factory.return_value = MagicMock(return_value=session)

            resp = client.post(
                "/api/v1/webhooks/google-drive",
                headers=_webhook_headers(channel_id="unknown-channel"),
            )
    assert resp.status_code == 202
    assert resp.json()["received"] == "unknown"
    mock_task.delay.assert_not_called()


def test_webhook_known_channel_enqueues_sync(client: TestClient) -> None:
    """Happy path: known channel, state=update → enqueue a sync task."""
    fake_source = MagicMock()
    fake_source.id = uuid.uuid4()
    with patch("app.tasks.sync.sync_source_task") as mock_task:
        mock_task.delay = MagicMock()
        with patch("app.api.v1.webhooks.get_session_factory") as mock_factory:
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.execute = AsyncMock(
                return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=fake_source))
            )
            mock_factory.return_value = MagicMock(return_value=session)

            resp = client.post(
                "/api/v1/webhooks/google-drive",
                headers=_webhook_headers(channel_id="known-channel", resource_state="update"),
            )
    assert resp.status_code == 202
    body = resp.json()
    assert body["received"] == "enqueued"
    assert body["source_id"] == str(fake_source.id)
    mock_task.delay.assert_called_once_with(str(fake_source.id), triggered_by="webhook")
