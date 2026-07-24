"""Real Cloudflare R2 implementation, via R2's S3-compatible API (boto3).

Like app/services/ai/gemini_provider.py, this is written carefully against
R2's documented S3-compatible surface but has NEVER been executed against
a live bucket — this sandbox's network egress allowlist doesn't include
Cloudflare's R2 endpoint domain. Treat it as reviewed-but-untested. To try
it for real: set STORAGE_PROVIDER=r2 and the four r2_* settings in .env
and restart — everything else (job tracking, versioning, endpoints,
frontend) works unchanged; only the provider swaps, same as the Gemini
provider.
"""

import asyncio

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.services.storage.base import StorageError, StorageProvider


class R2StorageProvider(StorageProvider):
    name = "cloudflare-r2"

    def __init__(self) -> None:
        self._bucket = settings.r2_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name="auto",  # R2 ignores region but boto3 requires one
        )

    async def save(self, *, key: str, content: bytes) -> str:
        def _put() -> None:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=content)

        try:
            await asyncio.to_thread(_put)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"R2 put_object failed for {key}: {exc}") from exc
        return key

    async def load(self, *, key: str) -> bytes:
        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()

        try:
            return await asyncio.to_thread(_get)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"R2 get_object failed for {key}: {exc}") from exc

    async def delete(self, *, key: str) -> None:
        def _delete() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"R2 delete_object failed for {key}: {exc}") from exc
