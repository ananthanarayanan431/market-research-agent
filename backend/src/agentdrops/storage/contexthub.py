"""Minio-backed raw-file storage for Context Hub uploads. Minio's client is synchronous, so
every call is wrapped in `asyncio.to_thread` to stay consistent with the rest of this async
codebase — this is the one place a blocking client is used."""

import asyncio
import io

from minio import Minio
from minio.error import S3Error

from agentdrops.config import Settings


class ContextHubStorage:
    def __init__(self, settings: Settings) -> None:
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_contexthub_bucket

    async def _ensure_bucket(self) -> None:
        exists = await asyncio.to_thread(self.client.bucket_exists, self._bucket)
        if exists:
            return
        try:
            await asyncio.to_thread(self.client.make_bucket, self._bucket)
        except S3Error as exc:
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._ensure_bucket()
        await asyncio.to_thread(
            self.client.put_object,
            self._bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type,
        )

    async def get(self, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, self._bucket, key)
        try:
            return await asyncio.to_thread(response.read)
        finally:
            response.close()
            response.release_conn()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self._bucket, key)
