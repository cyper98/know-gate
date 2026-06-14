"""Webhook handlers for source push notifications.

MVP: Google Drive push notifications only (Notion webhook is P1).

Drive sends a POST to this endpoint when a watched channel detects changes.
The X-Goog-Channel-Token header is the source ID (we set it when calling
`changes.watch`). The X-Goog-Resource-State header is "sync" for the initial
ping, "update" for subsequent changes, "exists" for state checks.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select

from app.db.models import Source
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/google-drive", status_code=status.HTTP_202_ACCEPTED)
async def google_drive_webhook(
    request: Request,
    x_goog_channel_id: str | None = Header(default=None),
    x_goog_channel_token: str | None = Header(default=None),
    x_goog_resource_id: str | None = Header(default=None),
    x_goog_resource_state: str | None = Header(default=None),
    x_goog_message_number: str | None = Header(default=None),
) -> dict:
    """Handle a Drive push notification.

    Behavior:
    - Look up the source by `X-Goog-Channel-Token` (we set this to source_id)
    - If `X-Goog-Resource-State` is "sync" (initial ping), return 200 fast
    - Otherwise, enqueue a sync task for the source

    Returns 202 even if the channel is unknown (Drive retries on non-2xx,
    and we don't want to spam logs during provider misconfigs).
    """
    if not x_goog_channel_token:
        # Drive always sends this; missing means it's not for us
        raise HTTPException(status_code=400, detail="missing X-Goog-Channel-Token")

    if x_goog_resource_state == "sync":
        # Initial channel-creation ping — nothing to do
        logger.info("drive_webhook_sync_ping", channel_id=x_goog_channel_id)
        return {"received": "sync"}

    # Verify the channel corresponds to a known source
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Source).where(
                Source.webhook_channel_id == x_goog_channel_id,
                Source.type == "google_drive",
            )
        )
        source = result.scalar_one_or_none()
        if source is None:
            # Channel ID not registered — Drive may be retrying; log + ack
            logger.warning(
                "drive_webhook_unknown_channel",
                channel_id=x_goog_channel_id,
                state=x_goog_resource_state,
            )
            return {"received": "unknown"}

    # Enqueue a sync
    from app.tasks.sync import sync_source_task

    sync_source_task.delay(str(source.id), triggered_by="webhook")
    logger.info(
        "drive_webhook_enqueued_sync",
        source_id=str(source.id),
        resource_state=x_goog_resource_state,
        message_number=x_goog_message_number,
    )
    return {"received": "enqueued", "source_id": str(source.id)}
