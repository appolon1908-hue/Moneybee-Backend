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

    async def presigned_download(
        self,
        *,
        object_key: str,
        expires_seconds: int = 300,
    ) -> str:
        client = self._client()
        return await asyncio.to_thread(
            client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": settings.object_storage_bucket,
                "Key": object_key,
            },
            ExpiresIn=min(max(expires_seconds, 60), 900),
        )
