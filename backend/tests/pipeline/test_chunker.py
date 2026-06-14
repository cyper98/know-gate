"""Unit tests for the chunker."""

from __future__ import annotations

import pytest

from app.pipeline.chunker import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TARGET_TOKENS,
    chunk_by_sections,
)
from app.pipeline.parser import ParsedDoc, Section


def _section(title: str, text: str, level: int = 1, page: int | None = None) -> Section:
    return Section(title=title, level=level, text=text, page_number=page)


def test_chunk_empty_parsed_doc_returns_empty_list() -> None:
    parsed = ParsedDoc(sections=[])
    assert chunk_by_sections(parsed) == []


def test_chunk_single_short_section_kept_as_one_chunk() -> None:
    parsed = ParsedDoc(sections=[_section("Intro", "Hello world.")])
    chunks = chunk_by_sections(parsed)
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].section_title == "Intro"
    assert chunks[0].chunk_index == 0
    assert chunks[0].token_count > 0


def test_chunk_multiple_short_sections_each_become_one_chunk() -> None:
    parsed = ParsedDoc(
        sections=[
            _section("H1", "First section body."),
            _section("H2", "Second section body."),
            _section("H3", "Third section body."),
        ]
    )
    chunks = chunk_by_sections(parsed)
    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert [c.section_title for c in chunks] == ["H1", "H2", "H3"]


def test_chunk_long_section_splits_with_recursive_fallback() -> None:
    long_text = ("This is a sentence. " * 500).strip()  # ~10K chars
    parsed = ParsedDoc(sections=[_section("Big", long_text)])
    chunks = chunk_by_sections(parsed, target_tokens=128, max_tokens=256)
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= 256
        assert c.section_title == "Big"


def test_chunk_respects_max_tokens_cap() -> None:
    long_text = "word " * 5000
    parsed = ParsedDoc(sections=[_section("X", long_text)])
    chunks = chunk_by_sections(parsed, target_tokens=64, max_tokens=128)
    for c in chunks:
        assert c.token_count <= 128


def test_chunk_invalid_target_tokens_raises() -> None:
    parsed = ParsedDoc(sections=[_section("A", "hi")])
    with pytest.raises(ValueError):
        chunk_by_sections(parsed, target_tokens=0)
    with pytest.raises(ValueError):
        chunk_by_sections(parsed, target_tokens=-1)


def test_chunk_max_less_than_target_raises() -> None:
    parsed = ParsedDoc(sections=[_section("A", "hi")])
    with pytest.raises(ValueError):
        chunk_by_sections(parsed, target_tokens=200, max_tokens=100)


def test_chunk_overlap_ratio_out_of_range_raises() -> None:
    parsed = ParsedDoc(sections=[_section("A", "hi")])
    with pytest.raises(ValueError):
        chunk_by_sections(parsed, overlap_ratio=1.0)
    with pytest.raises(ValueError):
        chunk_by_sections(parsed, overlap_ratio=-0.1)


def test_chunk_overlap_present_between_pieces() -> None:
    long_text = ("This is paragraph one. " * 100 + " " + "This is paragraph two. " * 100).strip()
    parsed = ParsedDoc(sections=[_section("Long", long_text)])
    chunks = chunk_by_sections(parsed, target_tokens=64, max_tokens=128, overlap_ratio=0.25)

    # Adjacent chunks (after the first) should share some text with the
    # previous one — at least one token of overlap.
    assert len(chunks) > 1
    for i in range(1, len(chunks)):
        prev_words = set(chunks[i - 1].text.split())
        curr_words = set(chunks[i].text.split())
        # At least one word in common (rough proxy for overlap)
        assert len(prev_words & curr_words) > 0


def test_chunk_skips_empty_sections() -> None:
    parsed = ParsedDoc(
        sections=[
            _section("A", "Real content here."),
            _section("B", "   \n\n  "),  # whitespace only
            _section("C", "More real content."),
        ]
    )
    chunks = chunk_by_sections(parsed)
    assert len(chunks) == 2
    assert [c.section_title for c in chunks] == ["A", "C"]


def test_chunk_preserves_page_number() -> None:
    parsed = ParsedDoc(
        sections=[_section("A", "Page 1 content", page=1), _section("B", "Page 2 content", page=2)]
    )
    chunks = chunk_by_sections(parsed)
    assert [c.page_number for c in chunks] == [1, 2]


def test_chunk_indexes_monotonic() -> None:
    parsed = ParsedDoc(
        sections=[
            _section("A", "alpha"),
            _section("B", "bravo"),
            _section("C", "charlie"),
        ]
    )
    chunks = chunk_by_sections(parsed)
    indices = [c.chunk_index for c in chunks]
    assert indices == sorted(indices)
    assert len(indices) == len(set(indices))  # all unique


def test_default_constants_match_architecture() -> None:
    """The architecture says 512 target, 1024 max — keep these in sync."""
    assert DEFAULT_TARGET_TOKENS == 512
    assert DEFAULT_MAX_TOKENS == 1024
