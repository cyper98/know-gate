"""S3-compatible MinIO client (boto3 async)."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import get_settings

from app.logging import get_logger

logger = get_logger(__name__)

_client: Any | None = None  # boto3 client (sync API; we'll wrap with run_in_executor if needed)


def get_s3_client() -> Any:
    """Lazy-init boto3 S3 client pointed at MinIO.

    NOTE: boto3 is sync.
    we use sync calls in async contexts via `asyncio.to_thread`.
    (sync engine) uses Celery (sync) so this is fine.
    may swap to aioboto3 if needed.
    """
    global _client
    if _client is None:
        settings = get_settings()
        _client = boto3.client(
            "s3",
            endpoint_url=settings.minio_url,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
            region_name="us-east-1",  # MinIO default
        )
        logger.info("minio_client_initialized", endpoint=settings.minio_url)
    return _client


async def check_minio() -> bool:
    """Verify MinIO is reachable. Returns True if list_buckets works."""
    import asyncio

    try:
        client = get_s3_client()
        await asyncio.to_thread(client.list_buckets)
        return True
    except (ClientError, EndpointConnectionError, Exception) as e:
        logger.error("minio_health_check_failed", error=str(e))
        return False


def reset_s3_client() -> None:
    """Reset cached client (for tests)."""
    global _client
    _client = None
