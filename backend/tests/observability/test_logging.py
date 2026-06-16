"""Tests that structured logging never leaks secret values.

Verifies the JSON-rendered structlog output for an event that contains
keys typically used to carry secrets (password, api_key, token, secret)
does not contain the secret value in the output.
"""

from __future__ import annotations

import io
import json
import logging

import structlog

from app.logging import configure_logging, get_logger


def _render_log(event: str, **kwargs) -> str:
    """Run a single log call through the JSON renderer and return the output."""
    buf = io.StringIO()
    configure_logging(log_level="INFO", json_output=True)
    # Replace the logger factory to write into our buffer.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=buf))
    logger = get_logger("test")
    logger.info(event, **kwargs)
    return buf.getvalue()


def test_password_value_is_not_in_log_output() -> None:
    """A `password` keyword argument is NOT serialized to the JSON log."""
    secret_password = "hunter2-very-secret"
    output = _render_log("user_login", user_id="u-1", password=secret_password)
    assert secret_password not in output
    # The event itself and the user_id are still present.
    assert "user_login" in output
    assert "u-1" in output


def test_api_key_value_is_not_in_log_output() -> None:
    """An `api_key` keyword argument is not present in the JSON log."""
    secret_key = "sk-verysecret-1234567890"
    output = _render_log("external_call", provider="openai", api_key=secret_key)
    assert secret_key not in output
    assert "openai" in output


def test_token_value_is_not_in_log_output() -> None:
    """A `token` keyword argument is not present in the JSON log."""
    secret_token = "eyJhbGciOiJIUzI1NiJ9.fake.payload"
    output = _render_log("auth_event", user_id="u-2", token=secret_token)
    assert secret_token not in output


def test_log_output_is_valid_json() -> None:
    """The log line is valid JSON, so Promtail can parse it."""
    output = _render_log("ok", event_name="ok", value=42)
    line = output.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "ok"
    assert parsed["value"] == 42
    # Reset stdlib handlers the test config touched.
    logging.getLogger().handlers.clear()
