"""Unit tests for the settings + audit-log API router."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.settings import SettingsUpdate

# === Settings schemas ===

def test_settings_update_all_optional() -> None:
    """Every field None = no-op (the endpoint short-circuits)."""
    body = SettingsUpdate()
    assert body.default_language is None
    assert body.allow_signup is None
    assert body.rate_limit_query_per_minute is None


def test_settings_update_bounds_retention_days() -> None:
    """Retention days: 1..3650 (matches the field validators)."""
    with pytest.raises(ValidationError):
        SettingsUpdate(feedback_retention_days=0)
    with pytest.raises(ValidationError):
        SettingsUpdate(audit_retention_days=10000)
    # Valid
    body = SettingsUpdate(feedback_retention_days=90, audit_retention_days=365)
    assert body.feedback_retention_days == 90


def test_settings_update_bounds_rate_limit() -> None:
    """rate_limit_query_per_minute: 1..10000."""
    with pytest.raises(ValidationError):
        SettingsUpdate(rate_limit_query_per_minute=0)
    with pytest.raises(ValidationError):
        SettingsUpdate(rate_limit_query_per_minute=20000)
    body = SettingsUpdate(rate_limit_query_per_minute=30)
    assert body.rate_limit_query_per_minute == 30


def test_settings_update_bounds_max_doc_size() -> None:
    """max_doc_size_mb: 1..1024 (1GB ceiling)."""
    with pytest.raises(ValidationError):
        SettingsUpdate(max_doc_size_mb=0)
    with pytest.raises(ValidationError):
        SettingsUpdate(max_doc_size_mb=2000)
    body = SettingsUpdate(max_doc_size_mb=50)
    assert body.max_doc_size_mb == 50


def test_settings_update_accepts_allow_signup_toggle() -> None:
    body = SettingsUpdate(allow_signup=True)
    assert body.allow_signup is True
    body = SettingsUpdate(allow_signup=False)
    assert body.allow_signup is False


def test_settings_update_language_codes_bounded() -> None:
    """ISO codes: 2..8 chars (en, vi, zh, etc.)."""
    with pytest.raises(ValidationError):
        SettingsUpdate(default_language="x")  # too short
    with pytest.raises(ValidationError):
        SettingsUpdate(default_language="a-very-long-code")  # too long
    body = SettingsUpdate(default_language="en", default_query_language="auto")
    assert body.default_language == "en"
