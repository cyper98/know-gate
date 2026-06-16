"""MinIO upload/download helpers (presigned URLs, streaming)."""

from __future__ import annotations

import asyncio
from typing import Any, BinaryIO

from app.config import get_settings
from app.storage.buckets import DOCUMENTS_BUCKET
from app.storage.client import get_s3_client

from app.logging import get_logger

logger = get_logger(__name__)


async def upload_doc(
    object_key: str,
    data: bytes | BinaryIO,
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
) -> str:
    """Upload a file to `documents` bucket. Returns the object key (path in bucket).

    Args:
        object_key: S3 key (e.g. "google_drive/doc123/file.pdf")
        data: file content (bytes or file-like)
        content_type: MIME type
        metadata: optional user metadata (key-value strings)
    """
    client = get_s3_client()
    extra_args: dict[str, Any] = {"ContentType": content_type}
    if metadata:
        extra_args["Metadata"] = metadata

    await asyncio.to_thread(
        client.put_object,
        Bucket=DOCUMENTS_BUCKET,
        Key=object_key,
        Body=data,
        **extra_args,
    )
    logger.info("minio_uploaded", bucket=DOCUMENTS_BUCKET, key=object_key)
    return object_key


async def download_doc(object_key: str) -> bytes:
    """Download a file from `documents` bucket. Returns the bytes."""
    client = get_s3_client()
    response = await asyncio.to_thread(
        client.get_object,
        Bucket=DOCUMENTS_BUCKET,
        Key=object_key,
    )
    async with response["Body"] as stream:
        data = await asyncio.to_thread(stream.read)
    logger.info("minio_downloaded", bucket=DOCUMENTS_BUCKET, key=object_key)
    return data


async def get_presigned_url(
    object_key: str,
    expires_seconds: int = 3600,
    method: str = "get_object",
) -> str:
    """Generate a presigned URL for direct browser access (preview/download).

    Args:
        object_key: S3 key
        expires_seconds: URL validity (default 1 hour)
        method: "get_object" (download) or "put_object" (upload)
    """
    client = get_s3_client()
    settings = get_settings()

    url = await asyncio.to_thread(
        client.generate_presigned_url,
        ClientMethod=method,
        Params={"Bucket": DOCUMENTS_BUCKET, "Key": object_key},
        ExpiresIn=expires_seconds,
    )
    # Replace internal endpoint with public endpoint (so browser can reach)
    if settings.minio_public_endpoint:
        url = url.replace(settings.minio_url, settings.minio_public_endpoint.rstrip("/"))
    return url


async def delete_doc(object_key: str) -> None:
    """Delete a file (soft: versioning keeps prior versions)."""
    client = get_s3_client()
    await asyncio.to_thread(
        client.delete_object,
        Bucket=DOCUMENTS_BUCKET,
        Key=object_key,
    )
    logger.info("minio_deleted", bucket=DOCUMENTS_BUCKET, key=object_key)


__all__ = [
    "delete_doc",
    "download_doc",
    "get_presigned_url",
    "upload_doc",
]
