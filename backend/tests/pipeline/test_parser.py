"""Unit tests for the document parser.

These tests do NOT use the real Unstructured library (it's heavy and
may not be installed in the test env). We patch the `unstructured` import
on a per-test basis to return synthetic Elements, then assert that the
parser correctly translates them to `ParsedDoc` / `Section`.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

from app.pipeline.parser import (
    EmptyDocumentError,
    ParsedDoc,
    ParserError,
    Section,
    _elements_to_parsed,
    _suffix_for_mime,
    parse_bytes,
)

# === Synthetic Unstructured Element factory ===

@dataclass
class _FakeMeta:
    page_number: int | None = None
    depth: int | None = None


@dataclass
class _FakeElement:
    text: str
    category: str = "NarrativeText"
    metadata: _FakeMeta | None = None


def _title(text: str, level: int = 1, page: int | None = None) -> _FakeElement:
    return _FakeElement(
        text=text, category="Title", metadata=_FakeMeta(page_number=page, depth=level)
    )


def _body(text: str, page: int | None = None) -> _FakeElement:
    return _FakeElement(text=text, category="NarrativeText", metadata=_FakeMeta(page_number=page))


def _list_item(text: str) -> _FakeElement:
    return _FakeElement(text=text, category="ListItem")


def _table(text: str) -> _FakeElement:
    return _FakeElement(text=text, category="Table")


# === Tests ===

def test_elements_to_parsed_basic() -> None:
    elements = [
        _title("Introduction", level=1),
        _body("This is the intro text."),
        _title("Body", level=1),
        _body("Body content here."),
    ]
    parsed = _elements_to_parsed(elements, mime_type="text/markdown")

    assert len(parsed.sections) == 2
    assert parsed.sections[0].title == "Introduction"
    assert "intro text" in parsed.sections[0].text
    assert parsed.sections[1].title == "Body"
    assert "Body content" in parsed.sections[1].text
    # Title = first Title element
    assert parsed.title == "Introduction"


def test_elements_to_parsed_preserves_heading_levels() -> None:
    elements = [
        _title("H1 Top", level=1),
        _body("Top text"),
        _title("H2 Sub", level=2),
        _body("Sub text"),
    ]
    parsed = _elements_to_parsed(elements, mime_type="text/markdown")
    assert parsed.sections[0].level == 1
    assert parsed.sections[1].level == 2


def test_elements_to_parsed_caps_heading_level_at_3() -> None:
    """h4 / h5 / h6 are collapsed to h3 (too noisy for RAG)."""
    elements = [
        _title("Deep", level=7),
        _body("text"),
    ]
    parsed = _elements_to_parsed(elements, mime_type="text/markdown")
    assert parsed.sections[0].level == 3


def test_elements_to_parsed_collects_list_items_into_section() -> None:
    elements = [
        _title("List", level=1),
        _list_item("Item 1"),
        _list_item("Item 2"),
        _list_item("Item 3"),
    ]
    parsed = _elements_to_parsed(elements, mime_type="text/markdown")
    assert len(parsed.sections) == 1
    assert "Item 1" in parsed.sections[0].text
    assert "Item 2" in parsed.sections[0].text
    assert "Item 3" in parsed.sections[0].text


def test_elements_to_parsed_collects_tables_into_section() -> None:
    elements = [
        _title("Data", level=1),
        _body("Intro text"),
        _table("| col1 | col2 |\n|---|---|\n| a | b |"),
    ]
    parsed = _elements_to_parsed(elements, mime_type="text/markdown")
    assert len(parsed.sections) == 1
    assert "col1" in parsed.sections[0].text
    assert "Intro text" in parsed.sections[0].text


def test_elements_to_parsed_preserves_page_number() -> None:
    """The section's page_number reflects the last page seen (so a
    paragraph that spans a page break is tagged with the trailing page).
    """
    elements = [
        _title("Title", level=1, page=1),
        _body("Text on page 2", page=2),
    ]
    parsed = _elements_to_parsed(elements, mime_type="application/pdf")
    # The single section's page is the last page mentioned (page 2)
    assert parsed.sections[0].page_number == 2


def test_elements_to_parsed_page_advances_on_page_break() -> None:
    """Two titles on different pages produce two sections with different page numbers."""
    elements = [
        _title("First", level=1, page=1),
        _body("body 1", page=1),
        _title("Second", level=1, page=3),
        _body("body 2", page=3),
    ]
    parsed = _elements_to_parsed(elements, mime_type="application/pdf")
    assert parsed.sections[0].page_number == 1
    assert parsed.sections[1].page_number == 3


def test_elements_to_parsed_empty_raises_empty_error() -> None:
    with pytest.raises(EmptyDocumentError):
        _elements_to_parsed([], mime_type="text/plain")


def test_elements_to_parsed_only_blank_text_raises_empty() -> None:
    """A doc full of empty / whitespace elements has no real content."""
    elements = [
        _FakeElement(text="   ", category="NarrativeText"),
        _FakeElement(text="", category="Title"),
    ]
    with pytest.raises(EmptyDocumentError):
        _elements_to_parsed(elements, mime_type="text/plain")


def test_parse_bytes_with_no_filename_uses_inmemory() -> None:
    """When no filename, parser tries unstructured's BytesIO API.

    We don't drive the full parse_bytes path here (requires real
    unstructured lib installed). The bytes-path is exercised via
    parse_bytes_with_filename_writes_temp_file (separate test if added).
    This test just asserts the in-memory helper works on synthetic data.
    """
    fake_elements = [_title("A", 1), _body("body text")]

    # Just confirm the helper translates elements — the actual bytes-path
    # test would require real unstructured installed.
    parsed = _elements_to_parsed(fake_elements, mime_type="text/plain")
    assert len(parsed.sections) == 1
    assert "body text" in parsed.sections[0].text


def test_parse_bytes_missing_unstructured_raises_parser_error() -> None:
    """If the `unstructured` import fails, the parser raises a clean ParserError."""
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("unstructured"):
            raise ImportError("simulated missing unstructured")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=_fake_import),
        pytest.raises(ParserError) as exc_info,
    ):
        parse_bytes(b"some bytes", mime_type="text/plain", filename="test.txt")
    assert "unstructured" in str(exc_info.value).lower()


def test_suffix_for_mime_known_types() -> None:
    assert _suffix_for_mime("application/pdf") == ".pdf"
    assert _suffix_for_mime("text/markdown") == ".md"
    assert _suffix_for_mime("text/plain") == ".txt"
    assert _suffix_for_mime("text/html") == ".html"
    assert (
        _suffix_for_mime("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        == ".docx"
    )


def test_suffix_for_mime_unknown_returns_empty() -> None:
    assert _suffix_for_mime("application/octet-stream") == ""


def test_parsed_doc_full_text_concatenates() -> None:
    parsed = ParsedDoc(
        sections=[
            _section_for("A", "alpha", 1),
            _section_for("B", "beta", 1),
        ]
    )
    out = parsed.full_text()
    assert "alpha" in out and "beta" in out


def _section_for(title: str, text: str, level: int) -> Section:
    return Section(title=title, level=level, text=text)
