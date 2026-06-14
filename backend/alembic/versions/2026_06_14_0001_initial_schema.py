"""initial schema: 14 tables (users, roles, user_roles, access_groups, user_groups,
documents, document_groups, chunks, sources, sync_jobs, queries, feedback,
audit_log, system_settings)

Revision ID: 0001
Revises:
Create Date: 2026-06-14

NOTE: This migration is hand-written for the initial schema. Future migrations
use `alembic revision --autogenerate -m "..."` from `app/db/models/`.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === pgcrypto for gen_random_uuid() ===
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # === users ===
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("language_pref", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_status", "users", ["status"], unique=False)
    op.create_index("ix_users_created_at", "users", ["created_at"], unique=False)

    # === roles ===
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=False)

    # === user_roles (M:N) ===
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("granted_by", sa.String(length=36), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_user_roles_user_id_users"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE", name="fk_user_roles_role_id_roles"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL", name="fk_user_roles_granted_by_users"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )

    # === access_groups ===
    op.create_table(
        "access_groups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL", name="fk_access_groups_created_by_users"),
        sa.UniqueConstraint("name", name="uq_access_groups_name"),
    )
    op.create_index("ix_access_groups_name", "access_groups", ["name"], unique=False)

    # === user_groups (M:N) ===
    op.create_table(
        "user_groups",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_user_groups_user_id_users"),
        sa.ForeignKeyConstraint(["group_id"], ["access_groups.id"], ondelete="CASCADE", name="fk_user_groups_group_id_access_groups"),
        sa.UniqueConstraint("user_id", "group_id", name="uq_user_group"),
        sa.PrimaryKeyConstraint("user_id", "group_id", name="pk_user_groups"),
    )

    # === documents ===
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="discovered"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("source", "source_id", name="uq_doc_source_id"),
    )
    op.create_index("ix_documents_source", "documents", ["source"], unique=False)
    op.create_index("ix_documents_source_id", "documents", ["source_id"], unique=False)
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"], unique=False)
    op.create_index("ix_documents_language", "documents", ["language"], unique=False)
    op.create_index("ix_documents_status", "documents", ["status"], unique=False)

    # === document_groups (M:N) ===
    op.create_table(
        "document_groups",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE", name="fk_document_groups_document_id_documents"),
        sa.ForeignKeyConstraint(["group_id"], ["access_groups.id"], ondelete="CASCADE", name="fk_document_groups_group_id_access_groups"),
        sa.UniqueConstraint("document_id", "group_id", name="uq_doc_group"),
        sa.PrimaryKeyConstraint("document_id", "group_id", name="pk_document_groups"),
    )

    # === chunks ===
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("section_title", sa.String(length=255), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("qdrant_point_id", sa.String(length=36), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE", name="fk_chunks_document_id_documents"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_doc_chunk_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index("ix_chunks_language", "chunks", ["language"], unique=False)
    op.create_index("ix_chunks_qdrant_point_id", "chunks", ["qdrant_point_id"], unique=False)

    # === sources ===
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("config_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL", name="fk_sources_created_by_users"),
    )
    op.create_index("ix_sources_type", "sources", ["type"], unique=False)
    op.create_index("ix_sources_status", "sources", ["status"], unique=False)

    # === sync_jobs ===
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("triggered_by", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("total_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_log", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE", name="fk_sync_jobs_source_id_sources"),
    )
    op.create_index("ix_sync_jobs_source_id", "sync_jobs", ["source_id"], unique=False)
    op.create_index("ix_sync_jobs_status", "sync_jobs", ["status"], unique=False)

    # === queries ===
    op.create_table(
        "queries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_language", sa.String(length=8), nullable=True),
        sa.Column("expanded_queries", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("retrieved_chunks", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="in_progress"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("llm_model", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_queries_user_id_users"),
    )
    op.create_index("ix_queries_user_id", "queries", ["user_id"], unique=False)
    op.create_index("ix_queries_status", "queries", ["status"], unique=False)
    op.create_index("ix_queries_created_at", "queries", ["created_at"], unique=False)

    # === feedback ===
    op.create_table(
        "feedback",
        sa.Column("query_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("rating", sa.String(length=32), nullable=False, server_default="good"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["query_id"], ["queries.id"], ondelete="CASCADE", name="fk_feedback_query_id_queries"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_feedback_user_id_users"),
        sa.PrimaryKeyConstraint("query_id", "user_id", name="pk_feedback"),
    )
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"], unique=False)

    # === audit_log (immutable) ===
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL", name="fk_audit_log_actor_id_users"),
    )
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"], unique=False)
    op.create_index("ix_audit_log_action", "audit_log", ["action"], unique=False)
    op.create_index("ix_audit_log_target_type", "audit_log", ["target_type"], unique=False)
    op.create_index("ix_audit_log_target_id", "audit_log", ["target_id"], unique=False)
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)

    # === system_settings (singleton, id=1) ===
    op.create_table(
        "system_settings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("default_language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("default_query_language", sa.String(length=8), nullable=False, server_default="auto"),
        sa.Column("feedback_retention_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("audit_retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("rate_limit_query_per_minute", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_doc_size_mb", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("allow_signup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # === seed singleton row (id=1) ===
    op.execute(
        "INSERT INTO system_settings (id, default_language) VALUES ('1', 'en') ON CONFLICT DO NOTHING;"
    )


def downgrade() -> None:
    # Drop in reverse order (children first)
    op.drop_table("system_settings")
    op.drop_table("audit_log")
    op.drop_table("feedback")
    op.drop_table("queries")
    op.drop_table("sync_jobs")
    op.drop_table("sources")
    op.drop_index("ix_chunks_qdrant_point_id", table_name="chunks")
    op.drop_index("ix_chunks_language", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("document_groups")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_language", table_name="documents")
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_index("ix_documents_source_id", table_name="documents")
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_table("documents")
    op.drop_table("user_groups")
    op.drop_index("ix_access_groups_name", table_name="access_groups")
    op.drop_table("access_groups")
    op.drop_table("user_roles")
    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_table("roles")
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
