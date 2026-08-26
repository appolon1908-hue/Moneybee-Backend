import os
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.portal_schemas import UploadSessionCreate


MAX_DOCUMENT_SIZE = 25 * 1024 * 1024
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class IssuedUpload:
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class VerifiedObject:
    etag: str | None
    size_bytes: int
    metadata: dict[str, str]


def _problem(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def validate_upload(payload: UploadSessionCreate) -> None:
    if payload.size_bytes > MAX_DOCUMENT_SIZE:
        raise _problem(
            "DOCUMENT_TOO_LARGE",
            f"Documents may not exceed {MAX_DOCUMENT_SIZE} bytes.",
            422,
        )
    if payload.mime_type.lower() not in ALLOWED_MIME_TYPES:
        raise _problem(
            "DOCUMENT_TYPE_NOT_ALLOWED",
            "The supplied document type is not accepted.",
            422,
        )
    if PurePath(payload.original_file_name).name != payload.original_file_name:
        raise _problem(
            "INVALID_FILE_NAME",
            "The original file name must not contain a path.",
            422,
        )


def build_storage_key(
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    session_id: uuid.UUID,
    original_file_name: str,
) -> str:
    safe_name = SAFE_NAME.sub("-", original_file_name).strip(".-") or "document"
    return (
        f"quarantine/{tenant_id}/{application_id}/{session_id}/"
        f"{safe_name[:200]}"
    )


def _bucket() -> str:
    bucket = os.getenv("MONEYBEE_DOCUMENT_BUCKET", "").strip()
    if not bucket:
        raise _problem(
            "DOCUMENT_STORAGE_NOT_CONFIGURED",
            "Secure document storage is not configured.",
            503,
        )
    return bucket


def _client() -> BaseClient:
    endpoint = os.getenv("MONEYBEE_DOCUMENT_S3_ENDPOINT") or None
    region = os.getenv("MONEYBEE_DOCUMENT_S3_REGION", "us-east-1")
    return boto3.client("s3", endpoint_url=endpoint, region_name=region)


def issue_presigned_upload(
    *,
    storage_key: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    session_id: uuid.UUID,
    expires_seconds: int = 900,
    client: BaseClient | None = None,
) -> IssuedUpload:
    s3 = client or _client()
    metadata = {
        "moneybee-session-id": str(session_id),
        "sha256": sha256.lower(),
        "expected-size": str(size_bytes),
        "scan-state": "pending",
    }
    parameters: dict[str, Any] = {
        "Bucket": _bucket(),
        "Key": storage_key,
        "ContentType": mime_type,
        "Metadata": metadata,
        "ServerSideEncryption": "AES256",
    }
    try:
        url = s3.generate_presigned_url(
            "put_object",
            Params=parameters,
            ExpiresIn=expires_seconds,
            HttpMethod="PUT",
        )
    except (BotoCoreError, ClientError) as exc:
        raise _problem(
            "DOCUMENT_STORAGE_UNAVAILABLE",
            "A secure upload URL could not be issued.",
            503,
        ) from exc
    headers = {
        "Content-Type": mime_type,
        "x-amz-server-side-encryption": "AES256",
        "x-amz-meta-moneybee-session-id": str(session_id),
        "x-amz-meta-sha256": sha256.lower(),
        "x-amz-meta-expected-size": str(size_bytes),
        "x-amz-meta-scan-state": "pending",
    }
    return IssuedUpload(url=url, headers=headers)


def verify_uploaded_object(
    *,
    storage_key: str,
    expected_size: int,
    expected_sha256: str,
    expected_session_id: uuid.UUID,
    client: BaseClient | None = None,
) -> VerifiedObject:
    s3 = client or _client()
    try:
        response = s3.head_object(Bucket=_bucket(), Key=storage_key)
    except (BotoCoreError, ClientError) as exc:
        raise _problem(
            "DOCUMENT_UPLOAD_NOT_FOUND",
            "The uploaded object could not be verified.",
            409,
        ) from exc
    metadata = {
        str(key).lower(): str(value)
        for key, value in (response.get("Metadata") or {}).items()
    }
    actual_size = int(response.get("ContentLength") or 0)
    if actual_size != expected_size:
        raise _problem(
            "DOCUMENT_SIZE_MISMATCH",
            "The uploaded document size does not match the upload session.",
            409,
        )
    if metadata.get("sha256", "").lower() != expected_sha256.lower():
        raise _problem(
            "DOCUMENT_HASH_MISMATCH",
            "The uploaded document hash does not match the upload session.",
            409,
        )
    if metadata.get("moneybee-session-id") != str(expected_session_id):
        raise _problem(
            "DOCUMENT_SESSION_MISMATCH",
            "The uploaded document does not belong to this upload session.",
            409,
        )
    return VerifiedObject(
        etag=(str(response.get("ETag")).strip('"') if response.get("ETag") else None),
        size_bytes=actual_size,
        metadata=metadata,
    )
