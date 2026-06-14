"""Shared fixtures for the auth test module.

Unit tests in this folder do NOT need the full app. The conftest only loads
the app / TestClient when an integration test requests it. This keeps the
unit suite fast and runnable without docker-compose.

For integration tests, the session-scoped `client` fixture sets valid env
vars before importing `app.main` (so Settings validation passes) and yields
a TestClient. Tests that hit real backends (PG, Redis, Qdrant, MinIO) should
be marked with `pytest.mark.integration` so they can be skipped via `-m "not integration"`.
"""

from __future__ import annotations

import base64
import os

import pytest

# === Valid env bootstrap (applied before any `from app.main import app`) ===

def _bootstrap_env() -> None:
    """Set required env vars so Settings() can construct. Idempotent."""
    # Valid 32-byte base64 encryption key (random per session, never committed)
    if not os.environ.get("KG_ENCRYPTION_KEY") or _is_invalid_b64_key(
        os.environ["KG_ENCRYPTION_KEY"]
    ):
        os.environ["KG_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode("ascii")

    # Domain + env defaults
    os.environ.setdefault("KG_ENV", "development")
    os.environ.setdefault("KG_DOMAIN", "localhost")
    os.environ.setdefault("KG_LOG_LEVEL", "WARNING")

    # JWT key paths (dev keys already exist in secrets/)
    os.environ.setdefault("JWT_PRIVATE_KEY_PATH", "./secrets/jwt_private.pem")
    os.environ.setdefault("JWT_PUBLIC_KEY_PATH", "./secrets/jwt_public.pem")

    # OAuth placeholders (never reached in unit tests, but Settings requires defaults)
    os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "")
    os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "")
    os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "")
    os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "")

    # DB / Redis / Qdrant / MinIO — values don't need to be reachable for unit tests
    os.environ.setdefault("KG_DB_HOST", "localhost")
    os.environ.setdefault("KG_DB_PORT", "5432")
    os.environ.setdefault("KG_DB_NAME", "knowgate_test")
    os.environ.setdefault("KG_DB_USER", "knowgate")
    os.environ.setdefault("KG_DB_PASSWORD", "test")
    os.environ.setdefault("REDIS_HOST", "localhost")
    os.environ.setdefault("REDIS_PORT", "6379")
    os.environ.setdefault("REDIS_PASSWORD", "")
    os.environ.setdefault("QDRANT_HOST", "localhost")
    os.environ.setdefault("QDRANT_PORT", "6333")
    os.environ.setdefault("QDRANT_API_KEY", "")
    os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
    os.environ.setdefault("MINIO_ACCESS_KEY", "knowgate")
    os.environ.setdefault("MINIO_SECRET_KEY", "knowgate")
    os.environ.setdefault("MINIO_SECURE", "false")
    os.environ.setdefault("LITELLM_HOST", "localhost")
    os.environ.setdefault("LITELLM_PORT", "4000")
    os.environ.setdefault("LITELLM_API_KEY", "")
    os.environ.setdefault("OPENAI_API_KEY", "")


def _is_invalid_b64_key(value: str) -> bool:
    """Return True if the value is not a valid 32-byte base64 key."""
    try:
        return len(base64.b64decode(value)) != 32
    except Exception:
        return True


_bootstrap_env()


# === Fixtures ===

@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient for integration tests. Requires backends up."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
