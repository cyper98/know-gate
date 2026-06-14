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
    "DOCUMENTS_BUCKET",
    "check_minio",
    "delete_doc",
    "download_doc",
    "get_presigned_url",
    "get_s3_client",
    "init_documents_bucket",
    "reset_s3_client",
    "upload_doc",
]
