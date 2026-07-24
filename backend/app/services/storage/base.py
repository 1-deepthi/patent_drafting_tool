from abc import ABC, abstractmethod


class StorageError(Exception):
    """Raised by a provider when a save/load/delete fails — caught by
    document_service, which records it as a Failed DocumentGenerationJob
    row rather than letting the request 500."""


class StorageProvider(ABC):
    """Storage abstraction (mirrors app/services/ai's Provider Interface
    pattern). Anything that can durably store and retrieve bytes under a
    key can implement this — local disk today (offline-safe default),
    Cloudflare R2 later, without touching document_service.py or the API
    layer at all.
    """

    #: Short identifier for audit/logging purposes.
    name: str

    @abstractmethod
    async def save(self, *, key: str, content: bytes) -> str:
        """Stores content under key. Returns the storage_key to persist on
        the Document/DocumentVersion row (may differ slightly from the
        input key, e.g. a bucket-qualified path). Raises StorageError on
        failure."""
        raise NotImplementedError

    @abstractmethod
    async def load(self, *, key: str) -> bytes:
        """Returns the stored bytes for key. Raises StorageError if the
        key doesn't exist or can't be read."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, *, key: str) -> None:
        """Deletes the object at key. Should not raise if the key is
        already gone — deletion is idempotent."""
        raise NotImplementedError
