"""fix naive datetime columns to TIMESTAMPTZ

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-18

Converts all naive TIMESTAMP columns to TIMESTAMP WITH TIME ZONE so that
asyncpg can accept timezone-aware datetime objects from Python code.

Affected columns:
- users.last_login_at
- documents.source_modified_at
- documents.indexed_at
- sources.last_sync_at
- sync_jobs.started_at
- sync_jobs.completed_at
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Columns to convert from TIMESTAMP to TIMESTAMPTZ
_COLUMNS_TO_FIX = [
    ("users", "last_login_at"),
    ("documents", "source_modified_at"),
    ("documents", "indexed_at"),
    ("sources", "last_sync_at"),
    ("sync_jobs", "started_at"),
    ("sync_jobs", "completed_at"),
]


def upgrade() -> None:
    for table, column in _COLUMNS_TO_FIX:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=True,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table, column in reversed(_COLUMNS_TO_FIX):
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
