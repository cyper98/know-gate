"""Unit tests for the base connector contract + shared types."""

from __future__ import annotations

import pytest

from app.sources.base import (
    BaseSourceConnector,
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
    SourceDoc,
)

# === SourceDoc dataclass ===

def test_source_doc_default_extra_is_independent_per_instance() -> None:
    """`field(default_factory=dict)` is required so instances don't share a dict."""
    a = SourceDoc(id="x", title="x", mime_type=None, modified_at=None, url=None)
    b = SourceDoc(id="y", title="y", mime_type=None, modified_at=None, url=None)
    a.extra["k"] = "v"
    assert "k" not in b.extra


def test_source_doc_is_frozen() -> None:
    """frozen=True means we cannot mutate after construction."""
    from dataclasses import FrozenInstanceError

    d = SourceDoc(id="x", title="x", mime_type=None, modified_at=None, url=None)
    with pytest.raises(FrozenInstanceError):
        d.id = "y"  # type: ignore[misc]


def test_source_doc_default_is_deleted_is_false() -> None:
    d = SourceDoc(id="x", title="x", mime_type=None, modified_at=None, url=None)
    assert d.is_deleted is False
    assert d.size_bytes is None


# === Exceptions ===

def test_connector_auth_error_is_connector_error() -> None:
    """`ConnectorAuthError` is a subclass of `ConnectorError` (so callers can
    catch the base and re-raise, etc.)."""
    assert issubclass(ConnectorAuthError, ConnectorError)
    e = ConnectorAuthError("token expired")
    assert str(e) == "token expired"


def test_connector_rate_limit_error_has_retry_after() -> None:
    e = ConnectorRateLimitError("429", retry_after=42)
    assert e.retry_after == 42
    assert "429" in str(e)


# === BaseSourceConnector contract ===

def test_base_connector_cannot_be_instantiated_directly() -> None:
    """ABC: calling `BaseSourceConnector(...)` directly must raise."""
    with pytest.raises(TypeError):
        BaseSourceConnector(source_id="x", config={})  # type: ignore[abstract]


def test_subclass_must_implement_all_abstract_methods() -> None:
    """A subclass missing any abstract method is also non-instantiable."""

    class HalfBaked(BaseSourceConnector):
        source_type = "test"

        async def validate_credentials(self) -> None:
            pass

        # missing: list_changes, fetch_doc

    with pytest.raises(TypeError):
        HalfBaked(source_id="x", config={})  # type: ignore[abstract]
