"""Unit tests for the Notion connector (mocked httpx)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.sources.base import (
    ConnectorAuthError,
    ConnectorRateLimitError,
)
from app.sources.notion import (
    NotionConnector,
    _blocks_to_markdown,
    _notion_page_to_source_doc,
    config_from_integration_token,
)

# === Constructor / config ===

def _make_connector(**overrides) -> NotionConnector:
    cfg = {"integration_token": "secret_test_token"}
    cfg.update(overrides)
    return NotionConnector(source_id="src-1", config=cfg)


def test_connector_stores_token() -> None:
    c = _make_connector()
    assert c.source_type == "notion"
    assert c.token == "secret_test_token"
    assert c.root_page_id is None


def test_connector_optional_root_page_id() -> None:
    c = _make_connector(root_page_id="page-abc")
    assert c.root_page_id == "page-abc"


def test_config_from_integration_token_omits_root_page_when_none() -> None:
    cfg = config_from_integration_token(integration_token="x")
    assert cfg == {"integration_token": "x"}
    assert "root_page_id" not in cfg


def test_config_from_integration_token_includes_root_page_when_set() -> None:
    cfg = config_from_integration_token(integration_token="x", root_page_id="r")
    assert cfg == {"integration_token": "x", "root_page_id": "r"}


# === _TokenBucket ===

@pytest.mark.asyncio
async def test_token_bucket_acquires_up_to_rate_immediately() -> None:
    from app.sources.notion import _TokenBucket

    bucket = _TokenBucket(rate=3, per_seconds=1.0)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    elapsed = time.monotonic() - start
    # 3 immediate acquires should be < 100ms
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_token_bucket_blocks_after_burst_exhausted() -> None:
    """After consuming the burst, the next acquire should wait."""
    from app.sources.notion import _TokenBucket

    bucket = _TokenBucket(rate=3, per_seconds=1.0)
    for _ in range(3):
        await bucket.acquire()
    # 4th acquire should wait (1 token / 3 per sec = 333ms)
    start = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - start
    assert elapsed > 0.05  # blocked for at least ~50ms (lenient bound)


# === _notion_page_to_source_doc ===

def test_notion_page_to_source_doc_extracts_title() -> None:
    page = {
        "id": "page-1",
        "object": "page",
        "last_edited_time": "2026-06-14T10:00:00.000Z",
        "url": "https://notion.so/page-1",
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": "My Page"}],
            },
        },
        "parent": {"type": "page_id", "page_id": "parent-1"},
    }
    doc = _notion_page_to_source_doc(page)
    assert doc.id == "page-1"
    assert doc.title == "My Page"
    assert doc.url == "https://notion.so/page-1"
    assert doc.modified_at is not None
    assert doc.extra["parent_type"] == "page_id"
    assert doc.extra["parent_id"] == "parent-1"


def test_notion_page_to_source_doc_untitled_when_no_title_property() -> None:
    page = {
        "id": "page-2",
        "object": "page",
        "last_edited_time": "2026-06-14T10:00:00.000Z",
        "url": None,
        "properties": {},
        "parent": {"type": "workspace", "workspace": True},
    }
    doc = _notion_page_to_source_doc(page)
    assert doc.title == "(untitled)"


# === _blocks_to_markdown ===

def test_blocks_to_markdown_handles_common_block_types() -> None:
    blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello"}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "item 1"}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "task"}], "checked": True}},
        {"type": "code", "code": {"rich_text": [{"plain_text": "x = 1"}], "language": "python"}},
        {"type": "divider", "divider": {}},
    ]
    md = _blocks_to_markdown(blocks)
    assert "# Title" in md
    assert "Hello" in md
    assert "- item 1" in md
    assert "- [x] task" in md
    assert "```python\nx = 1\n```" in md
    assert "---" in md


def test_blocks_to_markdown_empty_input_returns_empty_string() -> None:
    assert _blocks_to_markdown([]) == ""


# === HTTP error mapping ===

def _resp(status_code: int, text: str = "", headers: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.headers = headers or {}
    r.content = b"" if status_code >= 400 else b"{}"
    return r


@pytest.mark.asyncio
async def test_notion_get_maps_401_to_auth_error() -> None:
    c = _make_connector()
    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=_resp(401, "unauthorized"))
    mock_client.is_closed = False
    c._client = mock_client
    with pytest.raises(ConnectorAuthError):
        await c._get("/pages/abc")


@pytest.mark.asyncio
async def test_notion_get_maps_429_to_rate_limit_error() -> None:
    c = _make_connector()
    mock_client = MagicMock()
    mock_client.is_closed = False
    mock_client.get = AsyncMock(return_value=_resp(429, "limited", {"Retry-After": "10"}))
    mock_client.is_closed = False
    c._client = mock_client
    with pytest.raises(ConnectorRateLimitError) as exc:
        await c._get("/search")
    assert exc.value.retry_after == 10
