"""Supporting files (Phase 8): drawings, prior art, etc. uploaded against a
patent application. 10MB max / executables blocked, enforced here per
app/models/file.py's docstring. Any user who can view the application may
upload or download; delete is restricted to the uploader or an Admin.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.patents import _get_patent_or_404, _is_admin, _require_visible
from app.core.config import settings
from app.core.database import get_db
from app.models import File, User
from app.schemas.collaboration import FileOut
from app.services.audit import log_event
from app.services.file_service import FileValidationError, storage_key_for, validate_upload
from app.services.notification import notify
from app.services.storage import StorageError, get_storage_provider

router = APIRouter()

# NEW — see open item #28. Same rationale as CommentAdded in comments.py.
NOTIFICATION_TYPE_FILE_UPLOADED = "FileUploaded"


def _is_assigned_agent(user: User, patent) -> bool:
    """NEW (open item #27): the assigned Patent Agent may now also delete
    files on their own applications, not just the uploader or an Admin.
    Flag if this widening is wrong and delete should stay uploader/Admin-only."""
    return patent.assigned_patent_agent_id == user.id


async def _to_file_out(db: AsyncSession, f: File) -> FileOut:
    uploader_name = None
    if f.uploaded_by:
        uploader = await db.get(User, f.uploaded_by)
        uploader_name = uploader.full_name if uploader else None
    return FileOut(
        id=f.id,
        patent_application_id=f.patent_application_id,
        uploaded_by=f.uploaded_by,
        uploaded_by_name=uploader_name,
        original_file_name=f.original_file_name,
        mime_type=f.mime_type,
        file_size_bytes=f.file_size_bytes,
        created_at=f.created_at,
    )


@router.get("/{patent_id}/files", response_model=list[FileOut])
async def list_files(
    patent_id: int,
    response: Response,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    total = await db.scalar(
        select(func.count()).select_from(File)
        .where(File.patent_application_id == patent_id)
    )
    response.headers["X-Total-Count"] = str(total or 0)

    result = await db.execute(
        select(File)
        .where(File.patent_application_id == patent_id)
        .order_by(File.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [await _to_file_out(db, f) for f in result.scalars().all()]


@router.post("/{patent_id}/files", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    patent_id: int,
    upload: UploadFile,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    content = await upload.read()
    try:
        validate_upload(
            filename=upload.filename or "unnamed",
            size_bytes=len(content),
            max_bytes=settings.max_upload_size_bytes,
            blocked_extensions=settings.blocked_upload_extensions,
        )
    except FileValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    key = storage_key_for(patent_application_id=patent_id, filename=upload.filename or "unnamed")
    try:
        stored_key = await get_storage_provider().save(key=key, content=content)
    except StorageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to store file: {exc}") from exc

    file_row = File(
        patent_application_id=patent_id,
        uploaded_by=user.id,
        storage_key=stored_key,
        original_file_name=upload.filename,
        mime_type=upload.content_type,
        file_size_bytes=len(content),
    )
    db.add(file_row)
    await log_event(
        db, user_id=user.id, event_type="FILE_UPLOADED",
        entity_type="patent_application", entity_id=patent_id,
        metadata={"original_file_name": upload.filename, "size_bytes": len(content)},
    )
    recipient_ids = {
        uid for uid in (patent.created_by, patent.assigned_patent_agent_id)
        if uid is not None and uid != user.id
    }
    for uid in recipient_ids:
        await notify(
            db, user_id=uid, notification_type=NOTIFICATION_TYPE_FILE_UPLOADED,
            patent_application_id=patent_id,
        )
    await db.commit()
    await db.refresh(file_row)
    return await _to_file_out(db, file_row)


@router.get("/{patent_id}/files/{file_id}/download")
async def download_file(
    patent_id: int,
    file_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    file_row = await db.get(File, file_id)
    if file_row is None or file_row.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if not file_row.storage_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No stored content for this file")

    try:
        content = await get_storage_provider().load(key=file_row.storage_key)
    except StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stored file could not be read: {exc}") from exc

    media_type = file_row.mime_type or "application/octet-stream"
    filename = file_row.original_file_name or file_row.storage_key.rsplit("/", 1)[-1]
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{patent_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    patent_id: int,
    file_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    file_row = await db.get(File, file_id)
    if file_row is None or file_row.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if not (_is_admin(user) or file_row.uploaded_by == user.id or _is_assigned_agent(user, patent)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the uploader, the assigned Patent Agent, or an Admin may delete this file",
        )

    if file_row.storage_key:
        await get_storage_provider().delete(key=file_row.storage_key)
    await db.delete(file_row)
    await log_event(
        db, user_id=user.id, event_type="FILE_DELETED",
        entity_type="patent_application", entity_id=patent_id,
        metadata={"file_id": file_id, "original_file_name": file_row.original_file_name},
    )
    await db.commit()
