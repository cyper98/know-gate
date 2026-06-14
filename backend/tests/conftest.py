"""Root test-suite conftest.

This file is the FIRST conftest pytest loads (before any subdirectory
conftests). We set valid env vars here so that `from app.main import app`
or any other top-level import that triggers `Settings()` works in
the test sandbox without docker-compose up.

Why a root conftest:
- `app.config.Settings` validates `KG_ENCRYPTION_KEY` must decode to
  exactly 32 bytes. The dev `.env` ships with a 30-byte placeholder for
  docs purposes; CI / test sandbox don't have a real key.
- Setting the env var here (before subdirectory conftests or test imports)
  means Settings() finds a valid value in `os.environ` and never reads
  the broken `.env` value.
- Pydantic-settings priority: init kwargs > env vars > .env file. So a
  valid env var here wins over the .env file's invalid value.
"""

from __future__ import annotations

import base64
import os


def _is_invalid_b64_key(value: str) -> bool:
    """Return True if the value is not a valid 32-byte base64 key."""
    try:
        return len(base64.b64decode(value)) != 32
    except Exception:
        return True


# === Encryption key ===
if not os.environ.get("KG_ENCRYPTION_KEY") or _is_invalid_b64_key(
    os.environ["KG_ENCRYPTION_KEY"]
):
    os.environ["KG_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode("ascii")

# === Domain / env / log level ===
os.environ.setdefault("KG_ENV", "development")
os.environ.setdefault("KG_DOMAIN", "localhost")
os.environ.setdefault("KG_LOG_LEVEL", "WARNING")

# === JWT key paths (dev keys exist in secrets/) ===
os.environ.setdefault("JWT_PRIVATE_KEY_PATH", "./secrets/jwt_private.pem")
os.environ.setdefault("JWT_PUBLIC_KEY_PATH", "./secrets/jwt_public.pem")

# === OAuth (placeholders, never reached in unit tests) ===
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "")

# === Backends (values don't need to be reachable for unit tests) ===
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

# === Celery (in-memory for tests) ===
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
