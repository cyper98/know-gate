"""Unit tests for the no-result handler."""

from __future__ import annotations

from app.retrieval.no_result import (
    NoResultReason,
    build_no_result_message,
)


def test_no_result_message_in_vietnamese() -> None:
    r = build_no_result_message(NoResultReason.NO_RESULTS, language="vi")
    assert "không tìm thấy" in r.message
    assert r.reason == NoResultReason.NO_RESULTS


def test_no_result_message_in_english() -> None:
    r = build_no_result_message(NoResultReason.NO_RESULTS, language="en")
    assert "could not find" in r.message


def test_no_result_message_in_chinese() -> None:
    r = build_no_result_message(NoResultReason.NO_RESULTS, language="zh")
    assert "未找到" in r.message


def test_all_denied_message_includes_count() -> None:
    r = build_no_result_message(
        NoResultReason.ALL_DENIED, language="en", denied_count=7
    )
    assert "7" in r.message
    assert r.denied_count == 7


def test_unknown_language_falls_back_to_english() -> None:
    r = build_no_result_message(NoResultReason.NO_RESULTS, language="ja")
    assert "could not find" in r.message  # English fallback


def test_empty_query_message() -> None:
    r = build_no_result_message(NoResultReason.EMPTY_QUERY, language="en")
    assert "enter your question" in r.message.lower()


def test_suggestions_are_passed_through() -> None:
    suggestions = ["Doc A", "Doc B", "Doc C"]
    r = build_no_result_message(
        NoResultReason.NO_RESULTS, language="en", suggestions=suggestions
    )
    assert r.suggestions == suggestions
