"""MinIO bucket management (init `documents` bucket with versioning)."""

from __future__ import annotations

import asyncio
import logging

from botocore.exceptions import ClientError

from app.config import get_settings
from app.storage.client import get_s3_client

logger = logging.getLogger(__name__)

DOCUMENTS_BUCKET = "documents"


async def bucket_exists(bucket: str) -> bool:
    """Check if a bucket exists."""
    client = get_s3_client()
    try:
        await asyncio.to_thread(client.head_bucket, Bucket=bucket)
        return True
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchBucket", "NotFound"):
            return False
        raise


async def init_documents_bucket() -> None:
    """Create `documents` bucket with versioning enabled (idempotent)."""
    settings = get_settings()
    bucket = settings.minio_bucket
    client = get_s3_client()

    if not await bucket_exists(bucket):
        logger.info("minio_creating_bucket", bucket=bucket)
        await asyncio.to_thread(client.create_bucket, Bucket=bucket)
    else:
        logger.info("minio_bucket_exists", bucket=bucket)

    # Enable versioning (data protection — accidental deletes recoverable)
    try:
        await asyncio.to_thread(
            client.put_bucket_versioning,
            Bucket=bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )
        logger.info("minio_versioning_enabled", bucket=bucket)
    except ClientError as e:
        logger.warning("minio_versioning_failed", bucket=bucket, error=str(e))


__all__ = ["DOCUMENTS_BUCKET", "bucket_exists", "init_documents_bucket"]
