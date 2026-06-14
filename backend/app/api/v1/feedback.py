"""Feedback API endpoint (user-facing).

- POST /feedback — submit a rating (good / bad / source_missing) for
  one of the caller's past queries. The feedback row is used by
  the retrieval-tuning eval set and by the hot-topics widget.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.audit.log import log_event
from app.auth.permissions import CurrentUser
from app.db.enums import FeedbackRating
from app.db.models import Feedback, Query
from app.db.session import get_session_factory
from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    query_id: str
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    query_id: str
    rating: str
    comment: str | None = None


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def post_feedback(body: FeedbackRequest, user: CurrentUser) -> FeedbackResponse:
    """Submit feedback for one of the caller's past queries.

    The (query_id, user_id) pair is the primary key — re-submitting
    updates the existing row instead of creating a duplicate.
    """
    factory = get_session_factory()
    async with factory() as session:
        # Verify the query belongs to this user (privacy: can't rate
        # someone else's query)
        q = (
            await session.execute(
                select(Query).where(
                    Query.id == body.query_id, Query.user_id == user["id"]
                )
            )
        ).scalar_one_or_none()
        if q is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Query not found (or not owned by you)",
            )

        # Upsert by (query_id, user_id)
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(Feedback).values(
            query_id=body.query_id,
            user_id=user["id"],
            rating=body.rating.value,
            comment=body.comment,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["query_id", "user_id"],
            set_={
                "rating": stmt.excluded.rating,
                "comment": stmt.excluded.comment,
            },
        )
        await session.execute(stmt)
        await session.commit()

    # Best-effort audit log
    import asyncio
    asyncio.create_task(
        log_event(
            actor_id=user["id"],
            actor_email=None,
            action="query.feedback",
            target_type="query",
            target_id=body.query_id,
            detail=f"rating={body.rating.value}",
        )
    )

    return FeedbackResponse(
        query_id=body.query_id,
        rating=body.rating.value,
        comment=body.comment,
    )


__all__ = ["router"]
