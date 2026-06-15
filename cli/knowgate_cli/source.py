"""Source sub-commands (``kg source list`` / ``create`` / ``show`` / ``sync`` / ``delete``).

Mirrors the ``/api/v1/sources`` endpoints. All operations require
``manage_sources`` permission (admin role) — the API enforces this; the
CLI just surfaces 403s with a friendly message.

``kg source create`` is interactive:

- Google Drive: prompts for the OAuth flow result (the web UI exchanges
  the code and writes the tokens; for the CLI we accept a JSON blob
  with ``access_token``, ``refresh_token``, ``client_id``, ``client_secret``,
  ``token_expires_at``). Power users can ``--from-file <config.json>``
  to skip the prompts.
- Notion: prompts for the integration token, then the root page IDs
  to walk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .client import KnowGateClient
from .output import Output

# Known source types — mirrors ``app.db.enums.SourceType``.
SOURCE_TYPES: tuple[str, ...] = ("google_drive", "notion")


def list_sources(client: KnowGateClient, out: Output) -> list[dict[str, Any]]:
    """``kg source list`` — table view of all sources."""
    with out.spinner("Loading sources…"):
        rows = client.get("/sources")
    if out.json_mode:
        out.json(rows)
        return rows
    if not rows:
        out.info("No sources configured yet. Run `kg source create` to add one.")
        return []
    display_rows = [
        {
            "id": r.get("id", "")[:8],
            "name": r.get("name", ""),
            "type": r.get("type", ""),
            "status": r.get("status", ""),
            "last_sync": r.get("last_sync_at") or "—",
            "last_error": (r.get("last_error") or "")[:60],
        }
        for r in rows
    ]
    out.table(
        display_rows,
        columns=[
            ("id", "ID"),
            ("name", "Name"),
            ("type", "Type"),
            ("status", "Status"),
            ("last_sync", "Last Sync"),
            ("last_error", "Last Error"),
        ],
    )
    return rows


def show_source(client: KnowGateClient, out: Output, source_id: str) -> dict[str, Any]:
    """``kg source show <id>`` — single source detail."""
    with out.spinner(f"Loading source {source_id}…"):
        row = client.get(f"/sources/{source_id}")
    if out.json_mode:
        out.json(row)
        return row
    out.panel(
        "\n".join(
            f"[bold]{k.replace('_', ' ').title()}[/bold]: {v}"
            for k, v in row.items()
            if v is not None
        ),
        title=f"Source {row.get('id', source_id)[:8]}",
    )
    return row


def _prompt_drive_config(out: Output) -> dict[str, Any]:
    """Prompt for a Google Drive OAuth result.

    Expected fields (per the web UI's OAuth callback): ``access_token``,
    ``refresh_token``, ``client_id``, ``client_secret``, ``token_expires_at``
    (unix seconds; 0 = unknown).
    """
    out.info("Paste the Google Drive OAuth result. Required fields:")
    for f in ("access_token", "refresh_token", "client_id", "client_secret"):
        out.info(f"  • {f}")
    raw = out.prompt_text("OAuth JSON (or single-line)")
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
    else:
        # Fallback: assume "<access> <refresh>" space-separated
        parts = raw.split()
        if len(parts) < 2:
            raise ValueError("Expected JSON or '<access_token> <refresh_token>'")
        data = {
            "access_token": parts[0],
            "refresh_token": parts[1],
            "client_id": out.prompt_text("client_id"),
            "client_secret": out.prompt_text("client_secret"),
        }
    return {
        "access_token": data.get("access_token", ""),
        "refresh_token": data.get("refresh_token", ""),
        "client_id": data.get("client_id", ""),
        "client_secret": data.get("client_secret", ""),
        "token_expires_at": int(data.get("token_expires_at") or 0),
    }


def _prompt_notion_config(out: Output) -> dict[str, Any]:
    """Prompt for a Notion integration token + root page IDs."""
    token = out.prompt_text("Notion integration token")
    pages_raw = out.prompt_text("Comma-separated root page IDs (empty = all accessible)")
    pages = [p.strip() for p in pages_raw.split(",") if p.strip()]
    return {"integration_token": token, "root_page_ids": pages}


def create_source(
    client: KnowGateClient,
    out: Output,
    *,
    name: str | None = None,
    source_type: str | None = None,
    from_file: Path | None = None,
) -> dict[str, Any]:
    """``kg source create`` — interactive or file-driven.

    The flow:
    1. Pick a type (google_drive | notion) — or pass ``--type``.
    2. Provide the connector config — interactive prompt, or ``--from-file``.
    3. Provide a name — or pass ``--name``.
    4. POST /api/v1/sources.
    """
    if source_type is None:
        out.info("Source type:")
        for i, t in enumerate(SOURCE_TYPES, 1):
            out.info(f"  {i}. {t}")
        choice = out.prompt_text("Choose [1]").strip() or "1"
        try:
            idx = int(choice) - 1
            source_type = SOURCE_TYPES[idx]
        except (ValueError, IndexError):
            raise ValueError(f"Invalid choice. Pick 1..{len(SOURCE_TYPES)}") from None
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Unknown source type '{source_type}'. Valid: {SOURCE_TYPES}")

    if name is None:
        name = out.prompt_text("Display name")

    if from_file is not None:
        if not from_file.exists():
            raise FileNotFoundError(f"Config file not found: {from_file}")
        try:
            config = json.loads(from_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {from_file}: {exc}") from exc
    elif source_type == "google_drive":
        config = _prompt_drive_config(out)
    else:
        config = _prompt_notion_config(out)

    payload: dict[str, Any] = {"name": name, "type": source_type, "config": config}
    with out.spinner("Creating source…"):
        body = client.post("/sources", json=payload)
    if out.json_mode:
        out.json(body)
    else:
        out.success(f"Source created: {body.get('name')} (id={body.get('id', '')[:8]})")
    return body


def sync_source(client: KnowGateClient, out: Output, source_id: str) -> dict[str, Any]:
    """``kg source sync <id>`` — enqueue a manual sync job."""
    with out.spinner(f"Triggering sync for {source_id}…"):
        body = client.post(f"/sources/{source_id}/sync")
    if out.json_mode:
        out.json(body)
    else:
        out.success(f"Sync job queued (id={body.get('id', '')}).")
    return body


def delete_source(
    client: KnowGateClient,
    out: Output,
    source_id: str,
    *,
    yes: bool = False,
) -> None:
    """``kg source delete <id>`` — soft-delete (archive) with confirmation."""
    if not yes and not out.confirm(
        f"Archive source {source_id}? This hides it from active lists.",
        default=False,
    ):
        out.info("Cancelled.")
        return
    with out.spinner(f"Archiving source {source_id}…"):
        client.delete(f"/sources/{source_id}")
    out.success(f"Source {source_id} archived.")


__all__ = [
    "SOURCE_TYPES",
    "create_source",
    "delete_source",
    "list_sources",
    "show_source",
    "sync_source",
]
