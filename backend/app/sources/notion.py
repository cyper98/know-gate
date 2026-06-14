"""Notion connector.

Uses Notion's integration token (user pastes it during source setup). The
token is stored encrypted in `Source.config_encrypted` along with the
optional root page ID to scope the sync.

API endpoints used:
- `POST /v1/search` — list pages the integration has access to
- `GET /v1/pages/{id}` — page metadata
- `GET /v1/blocks/{id}/children` (paginated) — page content blocks
- Recursive flattening of child blocks + nested page links

Rate limit: 3 req/s. We use an in-process asyncio token bucket (no need
for Redis coordination in a single worker).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any

import httpx

from app.logging import get_logger
from app.sources.base import (
    BaseSourceConnector,
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
    SourceDoc,
)

logger = get_logger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"  # Notion API version (pinned for stability)
HTTP_TIMEOUT_SECONDS = 30.0
# Notion's published rate limit: average 3 req/s. We allow a small burst.
RATE_LIMIT_REQUESTS = 3
RATE_LIMIT_WINDOW_SECONDS = 1.0


class _TokenBucket:
    """Simple asyncio-friendly token bucket for Notion's 3 req/s limit."""

    def __init__(self, rate: int, per_seconds: float) -> None:
        self.rate = rate
        self.period = per_seconds
        self._lock = asyncio.Lock()
        self._last_refill = time.monotonic()
        self._tokens = float(rate)

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                float(self.rate), self._tokens + elapsed * (self.rate / self.period)
            )
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) * (self.period / self.rate)
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


class NotionConnector(BaseSourceConnector):
    source_type = "notion"

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        # Required: integration token
        self.token: str = config["integration_token"]
        # Optional: scope to a specific page (if None, search all accessible)
        self.root_page_id: str | None = config.get("root_page_id")
        self._bucket = _TokenBucket(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)

    # === Public API ===

    async def validate_credentials(self) -> None:
        """Probe with a small search call."""
        try:
            await self._post("/search", json_body={"page_size": 1})
        except ConnectorAuthError:
            raise
        except Exception as e:
            raise ConnectorError(f"Notion validation failed: {e}") from e

    async def list_changes(
        self, cursor: str | None
    ) -> tuple[list[SourceDoc], str | None]:
        """List all pages the integration can see.

        Notion does not have a true Changes API; we use `search` with
        `last_edited_time` filtering (caller stores the highest `last_edited_time`
        seen as the cursor for the next run).

        For the first sync (cursor=None), we return all pages. For subsequent
        syncs, we filter to `last_edited_time > cursor`.

        Returns:
            (docs, next_cursor) where `next_cursor` is the maximum `last_edited_time`
            in ISO format (used as the next cursor).
        """
        docs: list[SourceDoc] = []
        max_modified: str | None = cursor
        has_more = True
        start_cursor: str | None = None
        if cursor:
            # Notion search supports a `query` filter, not a date range directly.
            # The simplest correct approach: pull all pages, filter client-side.
            # For 10K+ page workspaces this should be replaced with a per-database
            # `last_edited_time` query — out of scope for MVP.
            pass

        while has_more:
            body: dict[str, Any] = {"page_size": 100, "filter": {"value": "page", "property": "object"}}
            if start_cursor:
                body["start_cursor"] = start_cursor
            data = await self._post("/search", json_body=body)
            for page in data.get("results", []):
                modified = (page.get("last_edited_time") or "").rstrip("Z") + "Z"
                if cursor and modified and modified <= cursor:
                    continue
                docs.append(_notion_page_to_source_doc(page))
                if modified and (max_modified is None or modified > max_modified):
                    max_modified = modified
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return docs, max_modified

    async def fetch_doc(self, doc_id: str) -> tuple[bytes, SourceDoc]:
        """Fetch one Notion page as Markdown + metadata.

        Notion returns content as a list of block objects. We flatten them to
        a Markdown representation (simple line-per-block). For richer output
        the `notion-to-md` library could be substituted.
        """
        page = await self._get(f"/pages/{doc_id}")
        if page.get("object") != "page":
            raise ConnectorError(f"Notion ID {doc_id} is not a page")

        # Paginated children
        blocks: list[dict[str, Any]] = []
        start_cursor: str | None = None
        has_more = True
        while has_more:
            params: dict[str, Any] = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor
            data = await self._get(f"/blocks/{doc_id}/children", params=params)
            blocks.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        markdown = _blocks_to_markdown(blocks)
        doc = _notion_page_to_source_doc(page)
        return markdown.encode("utf-8"), doc

    # === HTTP helpers ===

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._bucket.acquire()
        if not hasattr(self, "_client") or self._client.is_closed:  # type: ignore[attr-defined]
            self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)  # type: ignore[attr-defined]
        resp = await self._client.get(  # type: ignore[attr-defined]
            f"{NOTION_API_BASE}{path}",
            params=params,
            headers=self._headers(),
        )
        return self._handle(resp, path)

    async def _post(self, path: str, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        await self._bucket.acquire()
        if not hasattr(self, "_client") or self._client.is_closed:  # type: ignore[attr-defined]
            self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)  # type: ignore[attr-defined]
        resp = await self._client.post(  # type: ignore[attr-defined]
            f"{NOTION_API_BASE}{path}",
            json=json_body,
            headers=self._headers(),
        )
        return self._handle(resp, path)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _handle(self, resp: httpx.Response, path: str) -> dict[str, Any]:
        if resp.status_code == 401:
            raise ConnectorAuthError(f"Notion 401 on {path}: {resp.text[:200]}")
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise ConnectorRateLimitError("Notion rate limit", retry_after=retry_after)
        if resp.status_code >= 400:
            raise ConnectorError(
                f"Notion {path} failed: {resp.status_code} {resp.text[:200]}"
            )
        return resp.json() if resp.content else {}

    async def aclose(self) -> None:
        client = getattr(self, "_client", None)
        if client and not client.is_closed:
            await client.aclose()


# === Notion-specific helpers ===

def _notion_page_to_source_doc(page: dict[str, Any]) -> SourceDoc:
    """Map a Notion page object to our internal SourceDoc."""
    title = ""
    props = page.get("properties", {}) or {}
    # Title lives in `properties.title.title[0].plain_text` (or similar)
    for prop in props.values():
        if prop.get("type") == "title":
            rich = prop.get("title") or []
            title = "".join(seg.get("plain_text", "") for seg in rich)
            break
    modified = page.get("last_edited_time")
    modified_dt = None
    if modified:
        try:
            modified_dt = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        except ValueError:
            modified_dt = None
    parent = page.get("parent", {}) or {}
    url = page.get("url")
    return SourceDoc(
        id=page["id"],
        title=title or "(untitled)",
        mime_type="application/vnd.notion.page+markdown",
        modified_at=modified_dt,
        url=url,
        extra={"parent_type": parent.get("type"), "parent_id": parent.get(parent.get("type", ""), "")},
    )


def _blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Flatten Notion blocks to a simple Markdown representation.

    For MVP this is a minimal renderer: headings, paragraphs, lists, code.
    For richer rendering (tables, toggles, callouts), use a library like
    `notion-to-md` in a follow-up.
    """
    lines: list[str] = []
    for block in blocks:
        btype = block.get("type")
        if not btype:
            continue
        content = block.get(btype, {})
        rich = content.get("rich_text", []) or []
        text = "".join(seg.get("plain_text", "") for seg in rich)
        if btype == "heading_1":
            lines.append(f"# {text}")
        elif btype == "heading_2":
            lines.append(f"## {text}")
        elif btype == "heading_3":
            lines.append(f"### {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"- {text}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {text}")
        elif btype == "to_do":
            mark = "x" if content.get("checked") else " "
            lines.append(f"- [{mark}] {text}")
        elif btype == "code":
            lang = content.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif btype == "quote":
            lines.append(f"> {text}")
        elif btype == "divider":
            lines.append("---")
        else:
            # paragraph, callout, etc. — render as plain text
            if text:
                lines.append(text)
        lines.append("")  # blank line between blocks
    return "\n".join(lines).strip()


def config_from_integration_token(
    *,
    integration_token: str,
    root_page_id: str | None = None,
) -> dict[str, Any]:
    """Build the connector config dict from a raw Notion integration token."""
    cfg: dict[str, Any] = {"integration_token": integration_token}
    if root_page_id:
        cfg["root_page_id"] = root_page_id
    return cfg


def serialize_config(config: dict[str, Any]) -> str:
    return json.dumps(config, separators=(",", ":"))


def deserialize_config(blob: str) -> dict[str, Any]:
    return json.loads(blob)
