"""Validates and keys files uploaded against a patent application.

Per the File model's docstring, size/type limits (10MB max, executables
blocked) are enforced HERE at the application layer, not the database
layer — see app.core.config.settings.max_upload_size_bytes /
blocked_upload_extensions.
"""

import uuid
from pathlib import PurePosixPath


class FileValidationError(Exception):
    """Raised when an upload fails size or extension validation. Caught by
    the API layer and turned into a 422."""


def validate_upload(*, filename: str, size_bytes: int, max_bytes: int, blocked_extensions: tuple[str, ...]) -> None:
    if size_bytes <= 0:
        raise FileValidationError("Uploaded file is empty")
    if size_bytes > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise FileValidationError(f"File exceeds the {max_mb:.0f}MB upload limit")

    ext = PurePosixPath(filename).suffix.lower()
    if ext in blocked_extensions:
        raise FileValidationError(f"Files with a '{ext}' extension are not allowed")


def storage_key_for(*, patent_application_id: int, filename: str) -> str:
    """Generates a collision-safe storage key — UUID-prefixed so two
    uploads sharing an original filename never overwrite each other.
    original_file_name is stored separately on the File row and is what's
    shown to users / sent back on download."""
    safe_name = PurePosixPath(filename).name  # strips any path components
    return f"patents/{patent_application_id}/files/{uuid.uuid4().hex}_{safe_name}"
