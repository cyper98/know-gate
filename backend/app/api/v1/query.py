"""Query API endpoints (user-facing).

- POST /query              — ask a question, get answer + sources
- GET  /query/history      — list own past queries
- GET  /query/{id}         — read one past query (owner-only)

All endpoints require the caller to be authenticated (any role).
Permission filtering is enforced INSIDE the pipeline — the API
layer just passes `user.id` to it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi import Query as QueryParam
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.permissions import CurrentUser
from app.config import get_settings
from app.db.models import Query
from app.db.session import get_session_factory
from app.logging import get_logger
from app.retrieval.pipeline import run_query

logger = get_logger(__name__)
router = APIRouter(prefix="/query", tags=["query"])


# === Request / Response schemas ===

class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: str | None = Field(
        default=None,
        description="Optional ISO 639-1 override (vi, en, zh). "
        "If omitted, detected from the question text.",
    )
    bypass_cache: bool = Field(
        default=False,
        description="Admin debug: skip the semantic cache.",
    )


class CitationResponse(BaseModel):
    index: int
    chunk_id: str
    doc_id: str
    title: str
    section_title: str | None = None
    page_number: int | None = None
    source: str | None = None
    source_id: str | None = None
    url: str | None = None
    updated_at: str | None = None
    language: str | None = None
    score: float = 0.0
    snippet: str | None = None


class NoResultResponse(BaseModel):
    reason: str
    message: str
    suggestions: list[str] = Field(default_factory=list)
    denied_count: int = 0


class QueryResponse(BaseModel):
    query_id: str
    answer: str
    citations: list[CitationResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    no_answer: bool = False
    no_result: NoResultResponse | None = None
    latency_ms: int = 0
    cache_hit: bool = False
    llm_model: str | None = None
    cost_usd: float = 0.0
    status: str = "answered"


class QueryHistoryItem(BaseModel):
    id: str
    query_text: str
    query_language: str | None
    answer_text: str | None
    status: str
    latency_ms: int | None
    cost_usd: float | None
    llm_model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# === Helpers ===

async def _check_user_rate_limit(user_id: str) -> None:
    """Per-user rate limit (config: rate_limit_query_per_minute)."""
    settings = get_settings()
    from app.cache.helpers import check_user_rate_limit

    count, allowed = await check_user_rate_limit(
        user_id, window_seconds=60, limit=settings.rate_limit_query_per_minute
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded: {count} queries in the last 60s "
                f"(limit {settings.rate_limit_query_per_minute}/min). Try again shortly."
            ),
        )


# === Endpoints ===

@router.post("", response_model=QueryResponse, status_code=status.HTTP_200_OK)
async def post_query(
    body: QueryRequest,
    user: CurrentUser,
) -> QueryResponse:
    """Ask a question; return the LLM-generated answer + sources."""
    await _check_user_rate_limit(user["id"])
    result = await run_query(
        user_id=user["id"],
        query_text=body.question,
        user_language=body.language,
        bypass_cache=body.bypass_cache,
    )
    return _result_to_response(result)


@router.get("/history", response_model=list[QueryHistoryItem])
async def get_query_history(
    user: CurrentUser,
    limit: int = QueryParam(default=20, ge=1, le=100),
    offset: int = QueryParam(default=0, ge=0),
) -> list[QueryHistoryItem]:
    """List the caller's past queries (most recent first)."""
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(Query)
                .where(Query.user_id == user["id"])
                .order_by(Query.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        items = list(rows)
    return [QueryHistoryItem.model_validate(q) for q in items]


@router.get("/{query_id}", response_model=QueryHistoryItem)
async def get_query_by_id(
    query_id: str,
    user: CurrentUser,
) -> QueryHistoryItem:
    """Read one of the caller's own past queries."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Query).where(
                Query.id == query_id, Query.user_id == user["id"]
            )
        )
        q = result.scalar_one_or_none()
    if q is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query not found",
        )
    return QueryHistoryItem.model_validate(q)


def _result_to_response(result: Any) -> QueryResponse:
    """Convert a `QueryResult` (dataclass) to a `QueryResponse` (Pydantic)."""
    no_result = None
    if result.no_result is not None:
        no_result = NoResultResponse(
            reason=result.no_result.reason.value,
            message=result.no_result.message,
            suggestions=result.no_result.suggestions or [],
            denied_count=result.no_result.denied_count,
        )
    return QueryResponse(
        query_id=result.query_id,
        answer=result.answer,
        citations=[CitationResponse(**c.to_dict()) for c in result.citations],
        warnings=result.warnings,
        no_answer=result.no_answer,
        no_result=no_result,
        latency_ms=result.latency_ms,
        cache_hit=result.cache_hit,
        llm_model=result.llm_model,
        cost_usd=result.cost_usd,
        status=result.status,
    )


__all__ = ["router"]
