"""Google Drive connector.

Scopes (separate from the auth login OAuth scopes):
- `https://www.googleapis.com/auth/drive.readonly` — list + read files
- `https://www.googleapis.com/auth/drive.activity.read` — activity feed
  (alternative to Changes API; we use Changes for simplicity)

The connector stores the OAuth access + refresh token in the Source row's
`config_encrypted` field. `validate_credentials()` refreshes proactively if
the access token is within 5 minutes of expiry.

Sync flow:
- `list_changes(cursor)` — `changes.list` with `startPageToken` cursor
- `fetch_doc(id)` — `files.get?alt=media` for the raw bytes + `files.get` for
  metadata in the same call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
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

# Drive API base
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
# How many items per Changes API page (max 1000, 200 is a good default)
CHANGES_PAGE_SIZE = 200
# Refresh access token if it expires within this many seconds
TOKEN_REFRESH_GRACE_SECONDS = 300
# HTTP timeout for individual API calls
HTTP_TIMEOUT_SECONDS = 30.0


class GoogleDriveConnector(BaseSourceConnector):
    source_type = "google_drive"

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        super().__init__(source_id, config)
        # Required config fields (decrypted from Source.config_encrypted):
        self.access_token: str = config["access_token"]
        self.refresh_token: str | None = config.get("refresh_token")
        self.client_id: str = config["client_id"]
        self.client_secret: str = config["client_secret"]
        self.token_expires_at: int | None = config.get("token_expires_at")  # epoch seconds
        # Optional: filter to a specific folder (drive folder ID, "root" = all)
        self.folder_id: str | None = config.get("folder_id")

    # === Public API (BaseSourceConnector) ===

    async def validate_credentials(self) -> None:
        """Probe a small Drive call. Raises ConnectorAuthError on 401/403."""
        try:
            await self._drive_get("/files", params={"pageSize": 1})
        except ConnectorAuthError:
            raise
        except ConnectorError:
            raise
        except Exception as e:
            raise ConnectorError(f"Drive validation failed: {e}") from e

    async def list_changes(
        self, cursor: str | None
    ) -> tuple[list[SourceDoc], str | None]:
        """List files changed since the given page token (cursor).

        For the first sync, `cursor` is None — we call `changes.getStartPageToken`
        to get the baseline. For subsequent syncs, we pass the saved cursor.
        """
        if cursor is None:
            start = await self._drive_get("/changes/startPageToken")
            cursor = str(start.get("startPageToken"))

        docs: list[SourceDoc] = []
        page_token: str | None = cursor
        while page_token:
            params: dict[str, Any] = {
                "pageToken": page_token,
                "pageSize": CHANGES_PAGE_SIZE,
                "fields": "changes(fileId,removed,file(id,name,mimeType,modifiedTime,size,webViewLink,trashed)),newStartPageToken,nextPageToken",
                "spaces": "drive",
                "includeRemoved": "true",
            }
            data = await self._drive_get("/changes", params=params)

            for change in data.get("changes", []):
                file_id = change.get("fileId")
                if not file_id:
                    continue
                removed = bool(change.get("removed", False))
                file_meta = change.get("file") or {}
                is_trashed = bool(file_meta.get("trashed", False))
                if removed or is_trashed:
                    docs.append(
                        SourceDoc(
                            id=file_id,
                            title=file_meta.get("name", ""),
                            mime_type=file_meta.get("mimeType"),
                            modified_at=_parse_drive_time(file_meta.get("modifiedTime")),
                            url=file_meta.get("webViewLink"),
                            is_deleted=True,
                            extra={"source": "google_drive"},
                        )
                    )
                    continue
                # Optional folder filter
                if self.folder_id and not await self._is_in_folder(file_id, self.folder_id):
                    continue
                size = file_meta.get("size")
                docs.append(
                    SourceDoc(
                        id=file_id,
                        title=file_meta.get("name", ""),
                        mime_type=file_meta.get("mimeType"),
                        modified_at=_parse_drive_time(file_meta.get("modifiedTime")),
                        url=file_meta.get("webViewLink"),
                        size_bytes=int(size) if size else None,
                        extra={"source": "google_drive"},
                    )
                )

            page_token = data.get("nextPageToken")
            if not page_token:
                # New cursor for the next run
                return docs, data.get("newStartPageToken")

        return docs, cursor

    async def fetch_doc(self, doc_id: str) -> tuple[bytes, SourceDoc]:
        """Download raw file bytes + current metadata.

        The `alt=media` parameter triggers a binary download instead of metadata.
        We do a separate metadata call so we can return `SourceDoc` with the
        latest `modified_at` and `url` even if the download is partial.
        """
        meta = await self._drive_get(
            f"/files/{doc_id}",
            params={"fields": "id,name,mimeType,modifiedTime,size,webViewLink,trashed"},
        )
        if meta.get("trashed"):
            raise ConnectorError(f"Drive file {doc_id} is in trash")

        size = meta.get("size")
        size_bytes = int(size) if size else None

        # Stream the binary content. httpx handles gzip etc.
        await self._ensure_token_fresh()
        client = await self._http_client()
        try:
            resp = await client.get(
                f"{DRIVE_API_BASE}/files/{doc_id}",
                params={"alt": "media"},
                timeout=HTTP_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        except httpx.TimeoutException as e:
            raise ConnectorError(f"Drive download timeout: {e}") from e

        if resp.status_code == 401:
            await self._force_refresh()
            # Retry once
            resp = await client.get(
                f"{DRIVE_API_BASE}/files/{doc_id}",
                params={"alt": "media"},
                timeout=HTTP_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise ConnectorRateLimitError("Drive rate limit", retry_after=retry_after)
        if resp.status_code >= 400:
            raise ConnectorError(
                f"Drive download failed: {resp.status_code} {resp.text[:200]}"
            )

        doc = SourceDoc(
            id=doc_id,
            title=meta.get("name", ""),
            mime_type=meta.get("mimeType"),
            modified_at=_parse_drive_time(meta.get("modifiedTime")),
            url=meta.get("webViewLink"),
            size_bytes=size_bytes,
            extra={"source": "google_drive"},
        )
        return resp.content, doc

    # === Helpers ===

    async def _drive_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a Drive API JSON endpoint with auto-refresh on 401."""
        await self._ensure_token_fresh()
        client = await self._http_client()
        url = f"{DRIVE_API_BASE}{path}"
        try:
            resp = await client.get(
                url, params=params, timeout=HTTP_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        except httpx.TimeoutException as e:
            raise ConnectorError(f"Drive timeout on {path}: {e}") from e

        if resp.status_code == 401:
            await self._force_refresh()
            resp = await client.get(
                url, params=params, timeout=HTTP_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        if resp.status_code == 403:
            # Could be insufficient scope, daily quota, etc.
            raise ConnectorAuthError(
                f"Drive 403 on {path}: {resp.text[:200]}"
            )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            raise ConnectorRateLimitError("Drive rate limit", retry_after=retry_after)
        if resp.status_code >= 400:
            raise ConnectorError(
                f"Drive {path} failed: {resp.status_code} {resp.text[:200]}"
            )
        return resp.json() if resp.content else {}

    async def _is_in_folder(self, file_id: str, folder_id: str) -> bool:
        """Return True if the file lives directly under the given folder.

        For deep hierarchies the caller should index at the folder root and
        rely on access-group filtering downstream.
        """
        try:
            data = await self._drive_get(
                f"/files/{file_id}",
                params={"fields": "parents"},
            )
        except ConnectorError:
            return False
        parents = data.get("parents", [])
        return folder_id in parents

    async def _ensure_token_fresh(self) -> None:
        """Refresh the access token if it's close to expiring."""
        if self.token_expires_at is None or self.refresh_token is None:
            return
        now = int(datetime.now(UTC).timestamp())
        if self.token_expires_at - now > TOKEN_REFRESH_GRACE_SECONDS:
            return
        await self._force_refresh()

    async def _force_refresh(self) -> None:
        """Force-refresh the OAuth access token (one attempt; raises on failure)."""
        if not self.refresh_token:
            raise ConnectorAuthError("Drive refresh token missing; re-auth required")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code >= 400:
            raise ConnectorAuthError(
                f"Drive token refresh failed: {resp.status_code} {resp.text[:200]}"
            )
        data = resp.json()
        self.access_token = data["access_token"]
        self.token_expires_at = int(datetime.now(UTC).timestamp()) + int(
            data.get("expires_in", 3600)
        )
        logger.info("drive_token_refreshed", source_id=self.source_id)

    async def _http_client(self) -> httpx.AsyncClient:
        # Single shared client per connector instance. async, no event-loop
        # crossing because we create it lazily.
        if not hasattr(self, "_client") or self._client.is_closed:  # type: ignore[attr-defined]
            self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)  # type: ignore[attr-defined]
        return self._client  # type: ignore[attr-defined]

    async def aclose(self) -> None:
        client = getattr(self, "_client", None)
        if client and not client.is_closed:
            await client.aclose()


def _parse_drive_time(s: str | None) -> datetime | None:
    """Drive returns RFC 3339 (e.g. '2026-06-14T10:00:00.000Z')."""
    if not s:
        return None
    try:
        # Python 3.11+ fromisoformat handles 'Z' suffix
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# Convenience for the OAuth callback handler
def config_from_oauth_tokens(
    *,
    access_token: str,
    refresh_token: str | None,
    client_id: str,
    client_secret: str,
    expires_in: int,
    folder_id: str | None = None,
) -> dict[str, Any]:
    """Build the connector config dict from raw OAuth tokens."""
    cfg: dict[str, Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "token_expires_at": int(datetime.now(UTC).timestamp()) + int(expires_in),
    }
    if folder_id:
        cfg["folder_id"] = folder_id
    return cfg


def serialize_config(config: dict[str, Any]) -> str:
    """Serialize the config dict to a JSON string for storage in
    `Source.config_encrypted`. Caller encrypts the result with AES-256-GCM."""
    return json.dumps(config, separators=(",", ":"))


def deserialize_config(blob: str) -> dict[str, Any]:
    """Inverse of `serialize_config`."""
    return json.loads(blob)
