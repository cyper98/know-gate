"""Application configuration via environment variables (12-factor).

All env vars are atomic (per dev rules): no combined URLs, no defaults for required
values. App fails fast on missing required vars.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strict settings - missing required env var = fail fast."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === General ===
    kg_env: Literal["development", "staging", "production"] = "development"
    kg_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    kg_domain: str = "localhost"

    # === JWT (RS256) ===
    jwt_private_key_path: str = "./secrets/jwt_private.pem"
    jwt_public_key_path: str = "./secrets/jwt_public.pem"
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    # === Encryption (32 bytes, base64-encoded) ===
    kg_encryption_key: SecretStr = Field(...)

    # === PostgreSQL ===
    db_host: str = "postgres"
    db_port: int = 5432
    db_user: str = "knowgate"
    db_password: SecretStr = Field(...)
    db_name: str = "knowgate"

    # === Redis ===
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: SecretStr = SecretStr("")
    redis_db: int = 0

    # === Qdrant ===
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection: str = "chunks"

    # === MinIO ===
    minio_endpoint: str = "minio"
    minio_port: int = 9000
    minio_root_user: str = "knowgate"
    minio_root_password: SecretStr = Field(...)
    minio_bucket: str = "documents"
    minio_public_endpoint: str = "http://localhost:9000"

    # === LLM (LiteLLM proxy) ===
    litellm_host: str = "litellm"
    litellm_port: int = 4000
    litellm_master_key: SecretStr = SecretStr("sk-dev-key")
    litellm_default_model: str = "gpt-4o-mini"
    litellm_fallback_model: str = "ollama/llama3"

    # === OpenAI ===
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"

    # === Ollama ===
    ollama_base_url: str = "http://host.docker.internal:11434"

    # === Embedding (bge-m3) ===
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_device: Literal["cpu", "cuda"] = "cpu"
    embedding_batch_size: int = 8
    embedding_cache_ttl: int = 300

    # === OAuth - Google ===
    google_oauth_client_id: str = ""
    google_oauth_client_secret: SecretStr = SecretStr("")
    google_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    google_oauth_scopes: str = "openid email profile"

    # === OAuth - GitHub ===
    github_oauth_client_id: str = ""
    github_oauth_client_secret: SecretStr = SecretStr("")
    github_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/github/callback"
    github_oauth_scopes: str = "read:user user:email"

    # === SMTP ===
    smtp_host: str = "mailhog"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = "noreply@knowgate.local"
    smtp_tls: bool = False

    # === Rate Limits ===
    rate_limit_query_per_minute: int = 30
    rate_limit_login_per_15min: int = 5

    # === Search / Sync ===
    search_timeout_seconds: int = 10
    sync_interval_minutes: int = 5
    sync_max_concurrent: int = 3
    sync_batch_size: int = 100
    max_doc_size_mb: int = 50

    # === Query ===
    query_max_length: int = 2000
    query_summarize_threshold: int = 200
    query_top_k_vector: int = 20
    query_top_k_final: int = 5

    # === Feedback ===
    feedback_retention_days: int = 90

    # === Bootstrap Admin ===
    # These defaults exist ONLY for the `make seed` dev workflow; production
    # deployments must set them explicitly. The validator below rejects the
    # dev default in production.
    bootstrap_admin_email: str = "admin@knowgate.local"
    bootstrap_admin_password: SecretStr = SecretStr("ChangeMe123!")
    bootstrap_admin_name: str = "Admin"

    @field_validator("bootstrap_admin_password")
    @classmethod
    def _reject_dev_password_in_production(cls, v: SecretStr, info) -> SecretStr:
        """Refuse to start in production with the dev-default admin password."""
        env = (info.data or {}).get("kg_env", "development")
        if env == "production" and v.get_secret_value() == "ChangeMe123!":
            raise ValueError(
                "bootstrap_admin_password must be set explicitly in production "
                "(KG_BOOTSTRAP_ADMIN_PASSWORD env var); the dev default is not allowed."
            )
        return v

    # === Computed URLs (no env var - derived from atomic vars) ===

    @property
    def database_url_async(self) -> str:
        """Async SQLAlchemy URL for app."""
        return (
            f"postgresql+asyncpg://{self.db_user}:"
            f"{self.db_password.get_secret_value()}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic."""
        return (
            f"postgresql+psycopg2://{self.db_user}:"
            f"{self.db_password.get_secret_value()}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        pwd = self.redis_password.get_secret_value()
        auth = f":{pwd}@" if pwd else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def minio_url(self) -> str:
        return f"http://{self.minio_endpoint}:{self.minio_port}"

    @property
    def litellm_url(self) -> str:
        return f"http://{self.litellm_host}:{self.litellm_port}"

    @property
    def is_development(self) -> bool:
        return self.kg_env == "development"

    @property
    def is_production(self) -> bool:
        return self.kg_env == "production"

    @field_validator("kg_encryption_key")
    @classmethod
    def _validate_encryption_key(cls, v: SecretStr) -> SecretStr:
        """Encryption key must be a valid 32-byte base64 string."""
        import base64

        try:
            decoded = base64.b64decode(v.get_secret_value())
        except Exception as e:
            raise ValueError(f"KG_ENCRYPTION_KEY must be base64: {e}") from e
        if len(decoded) != 32:
            raise ValueError(
                f"KG_ENCRYPTION_KEY must decode to 32 bytes (got {len(decoded)})"
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings()  # type: ignore[call-arg]
