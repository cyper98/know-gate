"""Shared fixtures for source-connector tests.

Unit tests mock all external I/O (httpx responses, Redis, MinIO, DB).
Integration tests are out of scope here; they would require a live Drive
sandbox + Notion workspace + docker-compose up.
"""

from __future__ import annotations

import base64
import os

# === Env bootstrap (mirror of tests/auth/conftest.py) ===

def _bootstrap_env() -> None:
    if not os.environ.get("KG_ENCRYPTION_KEY") or _is_invalid_b64_key(
        os.environ["KG_ENCRYPTION_KEY"]
    ):
        os.environ["KG_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode("ascii")
    os.environ.setdefault("KG_ENV", "development")
    os.environ.setdefault("KG_DOMAIN", "localhost")
    os.environ.setdefault("KG_LOG_LEVEL", "WARNING")
    os.environ.setdefault("JWT_PRIVATE_KEY_PATH", "./secrets/jwt_private.pem")
    os.environ.setdefault("JWT_PUBLIC_KEY_PATH", "./secrets/jwt_public.pem")
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
    # Celery eager mode for tests
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"


def _is_invalid_b64_key(value: str) -> bool:
    try:
        return len(base64.b64decode(value)) != 32
    except Exception:
        return True


_bootstrap_env()
