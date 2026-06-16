"""Structured logging configuration with structlog + JSON output."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

# Keys whose VALUES must never appear in logs. The values are replaced
# with the string "[REDACTED]" before the JSON renderer runs.
# Matching is case-insensitive on the key name.
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "client_secret",
        "authorization",
        "private_key",
        "session",
    }
)
_REDACTION = "[REDACTED]"


def _scrub_secrets(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Processor: replace secret values in-place before serialization.

    Scans top-level keys of the event dict. Nested dicts / lists are
    scrubbed recursively so a leaked credential inside a payload is
    still caught.
    """
    for key in list(event_dict.keys()):
        if key.lower() in SECRET_KEYS:
            event_dict[key] = _REDACTION
            continue
        value = event_dict[key]
        if isinstance(value, dict):
            event_dict[key] = _scrub_secrets(_logger, _method, value)
        elif isinstance(value, list):
            event_dict[key] = [
                _scrub_secrets(_logger, _method, item) if isinstance(item, dict) else item
                for item in value
            ]
    return event_dict


def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog + stdlib logging.

    Args:
        log_level: DEBUG | INFO | WARNING | ERROR
        json_output: True for prod (JSON), False for dev (colored console)
    """
    # Shared processors
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _scrub_secrets,
    ]

    if json_output:
        # Production: JSON to stdout
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: pretty console output
        try:
            processors = [*shared_processors, structlog.dev.ConsoleRenderer(colors=True)]
        except ImportError:
            processors = [*shared_processors, structlog.processors.JSONRenderer()]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging (uvicorn, sqlalchemy, etc.) into structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Configure uvicorn to use our loggers
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = [logging.StreamHandler(sys.stdout)]


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger."""
    return structlog.get_logger(name)  # type: ignore[return-value]
