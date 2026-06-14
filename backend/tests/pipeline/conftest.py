"""Shared fixtures for the ingestion pipeline test module.

The unit tests here mock all heavy I/O (sentence-transformers,
unstructured, Qdrant, MinIO, DB). The integration tests
(`@pytest.mark.integration`) require docker-compose up.
"""

from __future__ import annotations

import base64
import os


def _bootstrap_env() -> None:
    """Set required env vars so Settings() can construct. Idempotent."""
    if not os.environ.get("KG_ENCRYPTION_KEY"):
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
    # Eager mode for Celery (no real broker needed in unit tests)
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
    # Eager mode still parses the broker URL — give it something sane so
    # the result backend derivation in app.celery_app doesn't break.
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")
    os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")


_bootstrap_env()
