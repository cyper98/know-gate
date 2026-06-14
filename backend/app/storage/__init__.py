"""Object storage package (MinIO S3-compatible)."""

from app.storage.buckets import DOCUMENTS_BUCKET, init_documents_bucket
from app.storage.client import check_minio, get_s3_client, reset_s3_client
from app.storage.uploader import (
    delete_doc,
    download_doc,
    get_presigned_url,
    upload_doc,
)

__all__ = [
    "check_minio",
    "get_s3_client",
    "reset_s3_client",
    "init_documents_bucket",
    "DOCUMENTS_BUCKET",
    "upload_doc",
    "download_doc",
    "get_presigned_url",
    "delete_doc",
]
