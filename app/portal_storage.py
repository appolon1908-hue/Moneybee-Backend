from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class PortalStorageUnavailable(RuntimeError):
    pass


class PortalStorageVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadDescriptor:
    url: str
    headers: dict[str, str]


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise PortalStorageUnavailable(f"Missing required storage setting: {name}")
    return value


def _client():
    endpoint_url = os.getenv("DOCUMENT_STORAGE_ENDPOINT_URL") or None
    region_name = os.getenv("DOCUMENT_STORAGE_REGION", "us-east-1")
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 2, "mode": "standard"},
            connect_timeout=3,
            read_timeout=5,
        ),
    )


def create_presigned_upload(
    *,
    object_key: str,
    content_type: str,
    sha256: str,
    expires_in: int = 600,
) -> UploadDescriptor:
    bucket = _required_environment("DOCUMENT_STORAGE_BUCKET")
    try:
        client = _client()
        url = client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket,
                "Key": object_key,
                "ContentType": content_type,
                "Metadata": {"sha256": sha256},
                "ServerSideEncryption": os.getenv(
                    "DOCUMENT_STORAGE_SERVER_SIDE_ENCRYPTION", "AES256"
                ),
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise PortalStorageUnavailable("Unable to issue a secure upload URL") from exc

    return UploadDescriptor(
        url=url,
        headers={
            "Content-Type": content_type,
            "x-amz-meta-sha256": sha256,
            "x-amz-server-side-encryption": os.getenv(
                "DOCUMENT_STORAGE_SERVER_SIDE_ENCRYPTION", "AES256"
            ),
        },
    )


def verify_uploaded_object(
    *,
    object_key: str,
    expected_size: int,
    expected_sha256: str,
) -> dict[str, Any]:
    bucket = _required_environment("DOCUMENT_STORAGE_BUCKET")
    try:
        result = _client().head_object(Bucket=bucket, Key=object_key)
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise PortalStorageVerificationError(
            "The uploaded object could not be verified"
        ) from exc

    actual_size = int(result.get("ContentLength", -1))
    actual_sha256 = str(result.get("Metadata", {}).get("sha256", "")).lower()
    if actual_size != expected_size:
        raise PortalStorageVerificationError("Uploaded object size does not match")
    if actual_sha256 != expected_sha256.lower():
        raise PortalStorageVerificationError("Uploaded object digest does not match")
    return {
        "etag": str(result.get("ETag", "")).strip('"'),
        "size_bytes": actual_size,
        "sha256": actual_sha256,
    }
