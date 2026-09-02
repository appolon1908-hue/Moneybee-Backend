import asyncio

import boto3
from botocore.config import Config

from app.config import settings
from app.integrations.base import ProviderError


class S3ObjectStorageAdapter:
    def _client(self):
        required = (
            settings.object_storage_endpoint,
            settings.object_storage_region,
            settings.object_storage_access_key,
            settings.object_storage_secret_key,
        )
        if not all(required) or not settings.object_storage_bucket:
            raise ProviderError("s3", "Object storage configuration is incomplete")
        return boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            region_name=settings.object_storage_region,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            config=Config(signature_version="s3v4"),
        )

    async def put_private(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> dict:
        client = self._client()
        await asyncio.to_thread(
            client.put_object,
            Bucket=settings.object_storage_bucket,
            Key=object_key,
            Body=content,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return {
            "bucket": settings.object_storage_bucket,
            "object_key": object_key,
        }

    async def get_private(self, *, object_key: str, version_id: str | None = None) -> bytes:
        client = self._client()
        params = {"Bucket": settings.object_storage_bucket, "Key": object_key}
        if version_id:
            params["VersionId"] = version_id
        try:
            response = await asyncio.to_thread(
                client.get_object,
                **params,
            )
        except Exception as exc:
            raise ProviderError("s3", "Stored object could not be retrieved") from exc
        return await asyncio.to_thread(response["Body"].read)

    async def delete_private(self, *, object_key: str) -> None:
        client = self._client()
        try:
            await asyncio.to_thread(
                client.delete_object,
                Bucket=settings.object_storage_bucket,
                Key=object_key,
            )
        except Exception as exc:
            raise ProviderError("s3", "Stored object could not be deleted") from exc

    async def presigned_upload(
        self,
        *,
        object_key: str,
        content_type: str,
        expires_seconds: int = 600,
    ) -> str:
        client = self._client()
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "put_object",
            Params={
                "Bucket": settings.object_storage_bucket,
                "Key": object_key,
                "ContentType": content_type,
                "ServerSideEncryption": "AES256",
            },
            ExpiresIn=min(max(expires_seconds, 60), 900),
        )

    async def head_private(self, *, object_key: str) -> dict:
        client = self._client()
        try:
            return await asyncio.to_thread(
                client.head_object,
                Bucket=settings.object_storage_bucket,
                Key=object_key,
            )
        except Exception as exc:
            raise ProviderError("s3", "Uploaded object could not be verified") from exc

    async def presigned_download(
        self,
        *,
        object_key: str,
        expires_seconds: int = 300,
        version_id: str | None = None,
    ) -> str:
        client = self._client()
        params = {"Bucket": settings.object_storage_bucket, "Key": object_key}
        if version_id:
            params["VersionId"] = version_id
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=min(max(expires_seconds, 60), 900),
        )
