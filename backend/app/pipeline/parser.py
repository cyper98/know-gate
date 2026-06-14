"""Document parser (Unstructured-based).

Wraps `unstructured.partition.auto.partition` to extract text + section
hierarchy from PDF / DOCX / PPTX / XLSX / MD / TXT / HTML. The output is
a `ParsedDoc` that the chunker consumes.

Design notes:
- Heading hierarchy is preserved (h1 / h2 / h3 levels) so the chunker
  can keep a section title in chunk metadata.
- Tables are extracted as Markdown (lossless for RAG).
- Empty / image-only PDFs (no text layer) raise `EmptyDocumentError` so
  the caller can mark the doc as failed and continue the batch.
- The unstructured import is lazy so the test suite can run without
  the heavy native deps (detectron2, tesseract) being installed.
"""

from __future__ import annotations

import io
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# Headings we extract as section boundaries.
# We keep this list narrow — h4 / h5 / h6 are too noisy for RAG.
_MAX_HEADING_LEVEL = 3


class ParserError(Exception):
    """Generic parse failure (caller can mark doc as FAILED)."""


class EmptyDocumentError(ParserError):
    """Document has no extractable text (e.g., scanned PDF)."""


@dataclass(slots=True)
class Section:
    """One section in a parsed document.

    `level` is 1 for h1, 2 for h2, etc. `None` for body text with no
    preceding heading. `text` is the joined paragraph / list / table
    content. `page_number` is the source page (1-indexed) when known.
    """

    title: str
    level: int | None
    text: str
    page_number: int | None = None


@dataclass(slots=True)
class ParsedDoc:
    """A parsed document ready for chunking."""

    sections: list[Section] = field(default_factory=list)
    title: str | None = None
    author: str | None = None
    created_at: str | None = None
    language: str | None = None  # ISO 639-1 (set by caller; parser does not detect)
    mime_type: str | None = None

    def full_text(self) -> str:
        """All section text joined by double newlines (for sanity / logging)."""
        return "\n\n".join(s.text for s in self.sections if s.text)


# === Public API ===

def parse_bytes(
    data: bytes,
    mime_type: str,
    filename: str | None = None,
) -> ParsedDoc:
    """Parse raw document bytes into a `ParsedDoc`.

    Unstructured's `partition` works best with a filename (it uses the
    extension to pick the right parser). When the caller has only bytes,
    we spill to a temp file under the original filename if provided.

    Args:
        data: raw file bytes
        mime_type: MIME type (e.g., "application/pdf")
        filename: optional original filename (used to pick the right parser)

    Raises:
        ParserError: any unstructured-level parse failure
        EmptyDocumentError: document has no text layer
    """
    if filename:
        # Persist to a temp file with the original extension so unstructured
        # picks the right parser. We clean up on the way out.
        suffix = Path(filename).suffix or _suffix_for_mime(mime_type)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            return _partition(tmp_path, mime_type)
        finally:
            import contextlib
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)
    # No filename: fall back to in-memory partition. Not all formats
    # support this (PDF requires a real path), so we may raise.
    return _partition_from_bytes(data, mime_type)


def parse_file(file_path: str | Path, mime_type: str) -> ParsedDoc:
    """Parse a file on disk."""
    return _partition(Path(file_path), mime_type)


# === Internals ===

def _partition(path: Path, mime_type: str) -> ParsedDoc:
    """Run unstructured.partition on a file path."""
    try:
        from unstructured.partition.auto import partition  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover - import-time guard
        raise ParserError(
            "unstructured is not installed; pip install 'unstructured[all-docs]'"
        ) from e

    try:
        elements = partition(filename=str(path))
    except Exception as e:
        raise ParserError(f"unstructured partition failed: {e}") from e

    return _elements_to_parsed(elements, mime_type)


def _partition_from_bytes(data: bytes, mime_type: str) -> ParsedDoc:
    """Run unstructured.partition on raw bytes (best-effort).

    Some formats (e.g., plain text, html) support in-memory parsing via
    `file=io.BytesIO(...)`. We try that first; on failure, raise.
    """
    try:
        from unstructured.partition.auto import partition  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover
        raise ParserError("unstructured is not installed") from e

    try:
        elements = partition(file=io.BytesIO(data))
    except Exception as e:
        raise ParserError(f"unstructured partition failed: {e}") from e

    return _elements_to_parsed(elements, mime_type)


def _elements_to_parsed(elements: list, mime_type: str) -> ParsedDoc:
    """Translate unstructured Elements into our ParsedDoc / Section model."""
    if not elements:
        raise EmptyDocumentError("unstructured returned no elements")

    sections: list[Section] = []
    current_title = "(untitled)"
    current_level: int | None = None
    current_page: int | None = None
    current_buf: list[str] = []

    def _flush() -> None:
        if not current_buf:
            return
        text = "\n\n".join(s for s in current_buf if s).strip()
        if text:
            sections.append(
                Section(
                    title=current_title,
                    level=current_level,
                    text=text,
                    page_number=current_page,
                )
            )
        current_buf.clear()

    for el in elements:
        # `category` distinguishes Title / NarrativeText / Table / ListItem ...
        cat = getattr(el, "category", "") or ""
        text = (getattr(el, "text", "") or "").strip()
        if not text:
            continue

        meta = getattr(el, "metadata", None)
        page = getattr(meta, "page_number", None) if meta is not None else None

        if cat == "Title":
            # New heading — close the current section, start a new one
            _flush()
            current_title = text[:255]  # Cap to fit the chunk column
            # Unstructured's depth metadata is sometimes set on Title elements
            depth = getattr(meta, "depth", None) if meta is not None else None
            current_level = _normalize_level(depth) if depth else 1
            current_page = page
            continue

        if cat in {"NarrativeText", "Text", "ListItem", "Table"}:
            current_buf.append(text)
            # If we see a body element with a known page, advance the
            # section's page number (paragraphs after a page break
            # belong to the new page even if no new title was emitted).
            if page is not None:
                current_page = page
            continue

        # Unknown category — keep its text but don't change section
        current_buf.append(text)

    _flush()

    if not sections:
        raise EmptyDocumentError("document had no extractable text")

    # Document title = first Title element (or filename fallback handled by caller)
    title = next((s.title for s in sections if s.title and s.title != "(untitled)"), None)

    return ParsedDoc(
        sections=sections,
        title=title,
        mime_type=mime_type,
    )


def _normalize_level(depth: int | None) -> int | None:
    if depth is None or depth < 1:
        return 1
    return min(int(depth), _MAX_HEADING_LEVEL)


def _suffix_for_mime(mime_type: str) -> str:
    """Best-effort extension guess for in-memory bytes (used as temp file suffix)."""
    mapping = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/markdown": ".md",
        "text/plain": ".txt",
        "text/html": ".html",
    }
    return mapping.get(mime_type, "")


if TYPE_CHECKING:  # pragma: no cover - typing only
    pass  # type: ignore[import-untyped]


__all__ = [
    "EmptyDocumentError",
    "ParsedDoc",
    "ParserError",
    "Section",
    "parse_bytes",
    "parse_file",
]
