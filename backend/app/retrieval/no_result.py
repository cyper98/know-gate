"""No-result handler.

When the hybrid retriever returns zero candidates, the pipeline
calls this module to:
- Pick the right user-facing message (E5 / E9 from the brainstorm)
- Suggest up to 3-5 similar popular documents from the feedback log

Two distinct cases:
1. `NO_RESULTS` — the index has nothing matching at all (user is in
   valid groups, but the corpus doesn't cover the topic). Message
   says "couldn't find" + suggests popular docs.
2. `ALL_DENIED` — there are matches, but the user's groups ∩
   document groups is empty (data leak defense in depth). Message
   says "N results exist, but you don't have permission" + shows
   the count (does NOT show the titles, that would be a leak).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.logging import get_logger

logger = get_logger(__name__)


class NoResultReason(StrEnum):
    """Why we couldn't answer. Values stored in `Query.warnings` JSONB."""

    NO_RESULTS = "no_results"  # Nothing in the index matched
    ALL_DENIED = "all_denied"  # Matches exist, but user has no access
    EMPTY_QUERY = "empty_query"  # User submitted an empty query


# Per-language fallback messages (E5 wording from the brainstorm).
# Keep them short and in the user's language.
_DEFAULT_MESSAGES = {
    "vi": {
        "no_results": "Tôi không tìm thấy thông tin phù hợp trong các tài liệu hiện có.",
        "all_denied": "Có {n} kết quả liên quan, nhưng bạn không có quyền truy cập.",
        "empty_query": "Vui lòng nhập câu hỏi của bạn.",
    },
    "en": {
        "no_results": "I could not find relevant information in the available sources.",
        "all_denied": "There are {n} related results, but you don't have permission to view them.",
        "empty_query": "Please enter your question.",
    },
    "zh": {
        "no_results": "在当前文档中未找到相关信息。",
        "all_denied": "有 {n} 条相关结果，但您没有访问权限。",
        "empty_query": "请输入您的问题。",
    },
}


@dataclass(slots=True)
class NoResultResponse:
    """What the UI should render when the answer is empty."""

    reason: NoResultReason
    message: str
    suggestions: list[str] = None  # type: ignore[assignment]
    denied_count: int = 0  # For ALL_DENIED: how many were filtered out


def build_no_result_message(
    reason: NoResultReason,
    *,
    language: str = "en",
    denied_count: int = 0,
    suggestions: Sequence[str] | None = None,
) -> NoResultResponse:
    """Pick the right user-facing message for the given reason.

    Args:
        reason: which no-result branch we're in
        language: ISO 639-1 code; falls back to English on unknown
        denied_count: for ALL_DENIED — the number of results hidden
        suggestions: for NO_RESULTS — popular doc titles to suggest
            (the pipeline fills these from the feedback log)

    Returns:
        A `NoResultResponse` with the localized message + suggestions.
    """
    lang = language if language in _DEFAULT_MESSAGES else "en"
    msgs = _DEFAULT_MESSAGES[lang]
    template = msgs[reason.value]
    message = template.format(n=denied_count) if "{n}" in template else template

    return NoResultResponse(
        reason=reason,
        message=message,
        suggestions=list(suggestions or []),
        denied_count=denied_count,
    )


__all__ = [
    "NoResultReason",
    "NoResultResponse",
    "build_no_result_message",
]
