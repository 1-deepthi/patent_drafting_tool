"""Firebase Cloud Storage helpers for uploads and generated documents."""
from app.core.firebase import FirebaseNotConfigured, bucket


class StorageError(RuntimeError):
    pass


def put_bytes(path: str, data: bytes, content_type: str | None = None) -> None:
    try:
        blob = bucket().blob(path)
        blob.upload_from_string(data, content_type=content_type)
    except FirebaseNotConfigured as exc:
        raise StorageError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface a usable API error
        raise StorageError(f"Could not write to Firebase Storage: {exc}") from exc


def read_bytes(path: str) -> bytes:
    try:
        return bucket().blob(path).download_as_bytes()
    except FirebaseNotConfigured as exc:
        raise StorageError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise StorageError(f"Could not read from Firebase Storage: {exc}") from exc


def delete_path(path: str) -> None:
    if not path:
        return
    try:
        bucket().blob(path).delete()
    except FirebaseNotConfigured:
        return
    except Exception:  # noqa: BLE001 - deleting an already-missing object is fine
        return
