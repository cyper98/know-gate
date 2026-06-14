"""add Source sync_cursor + webhook fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14

Adds four columns to `sources` to support the source-connectors work block:
- `sync_cursor` (TEXT, nullable) — opaque per-provider sync cursor
  (Drive Changes API page token, Notion last_edited_time, etc.)
- `webhook_channel_id` (VARCHAR(128), nullable, indexed) — Drive push
  notification channel ID
- `webhook_resource_id` (VARCHAR(128), nullable) — Drive resource state
- `webhook_expires_at` (TIMESTAMPTZ, nullable) — Drive channel expiry (7 days)

This migration was created retroactively after the model was updated in the
same work block. Without it, `alembic upgrade head` against a fresh DB would
fail at the first sync (column does not exist).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("sync_cursor", sa.Text(), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("webhook_channel_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("webhook_resource_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("webhook_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_sources_webhook_channel_id",
        "sources",
        ["webhook_channel_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sources_webhook_channel_id", table_name="sources")
    op.drop_column("sources", "webhook_expires_at")
    op.drop_column("sources", "webhook_resource_id")
    op.drop_column("sources", "webhook_channel_id")
    op.drop_column("sources", "sync_cursor")
