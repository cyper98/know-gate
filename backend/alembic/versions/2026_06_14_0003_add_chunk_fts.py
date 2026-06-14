"""add PostgreSQL FTS support to chunks (tsvector + GIN index)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14

The retrieval work block needs keyword (BM25-ish) search as the
lexical half of the hybrid retriever. PostgreSQL's `tsvector` +
GIN index is the right tool — no extra service to operate, lives in
the same DB the chunk rows already occupy.

We add a `tsv` column (generated from `chunk_text`) and a GIN index
on it. The generation is `STORED` so the planner can use the index
without evaluating the expression at query time.

We use the `simple` text-search config (not `english`) because the
chunks are multilingual vi/en/zh — `simple` does no stemming but
preserves diacritics, which is what we want for vi/zh matching. For
en we lose stemming (e.g., "running" won't match "run") but the
bge-m3 vector leg compensates.

This migration is a no-op for SQLite / test environments that
disable FTS — the column is added regardless but the GIN index
creation is PG-only. Tests use the SQLAlchemy model in-memory and
the keyword path falls back to `LIKE` when `tsv` is unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the generated column (PostgreSQL `GENERATED ALWAYS AS ... STORED`)
    op.execute(
        "ALTER TABLE chunks ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(chunk_text, ''))) STORED"
    )

    # 2. GIN index for fast keyword lookup (PG-only; wrapped in try so
    #    SQLite test envs don't blow up — they just don't get the index).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_chunks_tsv",
            "chunks",
            ["tsv"],
            unique=False,
            postgresql_using="gin",
        )
    else:
        # Non-PG: best-effort B-tree fallback so the test env still works.
        op.create_index("ix_chunks_tsv", "chunks", ["tsv"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chunks_tsv", table_name="chunks")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")
