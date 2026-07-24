from app.core.config import settings
from app.services.storage.base import StorageProvider
from app.services.storage.local_provider import LocalStorageProvider
from app.services.storage.r2_provider import R2StorageProvider


def get_storage_provider() -> StorageProvider:
    if settings.storage_provider == "r2":
        return R2StorageProvider()
    return LocalStorageProvider()
