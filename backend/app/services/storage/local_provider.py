"""Offline-safe default storage provider — writes to a local directory on
the same filesystem the API runs on. This is what every live-verification
in this project has run against, since this sandbox (like Google's Gemini
API) has no network route to Cloudflare R2's endpoint. NOT suitable for a
real multi-instance deployment (Koyeb backend instances don't share a
disk) — it exists so the rest of the document-generation pipeline
(job tracking, versioning, DOCX/PDF conversion) can be built and verified
today, with a real swap to R2 needing only R2StorageProvider's REST calls
tested against a live account. See app/services/storage/r2_provider.py.
"""

import asyncio
from pathlib import Path

from app.core.config import settings
from app.services.storage.base import StorageError, StorageProvider


class LocalStorageProvider(StorageProvider):
    name = "local-disk"

    def __init__(self) -> None:
        self._root = Path(settings.local_storage_path)
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Guard against path traversal via a crafted key — keys are always
        # generated server-side (see document_service.storage_key_for), but
        # defend anyway since this touches the filesystem.
        clean = key.lstrip("/")
        path = (self._root / clean).resolve()
        if self._root.resolve() not in path.parents and path != self._root.resolve():
            raise StorageError(f"Refusing to write outside storage root: {key}")
        return path

    async def save(self, *, key: str, content: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            path.write_bytes(content)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            raise StorageError(f"Failed to write {key}: {exc}") from exc
        return key

    async def load(self, *, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise StorageError(f"No stored object at {key}")

        def _read() -> bytes:
            return path.read_bytes()

        try:
            return await asyncio.to_thread(_read)
        except OSError as exc:
            raise StorageError(f"Failed to read {key}: {exc}") from exc

    async def delete(self, *, key: str) -> None:
        path = self._resolve(key)

        def _delete() -> None:
            path.unlink(missing_ok=True)

        await asyncio.to_thread(_delete)
