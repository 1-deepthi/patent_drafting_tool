"""Document generation (workflow items 9/10): a Patent Agent (or
Admin/Super Admin) clicks "Generate Documents" once AI drafting (Phase 6)
is complete for every section. Runs as a tracked DocumentGenerationJob —
see app/services/document_service.py for why this is synchronous today
(same as Phase 6's AI generation) rather than a real Celery task, and for
the retry-always-creates-a-new-job rule.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.patents import _get_patent_or_404, _is_admin, _require_visible
from app.core.database import get_db
from app.models import Document, DocumentGenerationJob, DocumentVersion, User
from app.schemas.documents import (
    DocumentGenerationJobOut,
    DocumentOut,
    DocumentVersionOut,
    GenerateDocumentRequest,
)
from app.services.audit import log_event
from app.services.document_service import (
    DOCUMENT_TYPES,
    DocumentGenerationNotAllowed,
    can_generate_documents,
    run_generation_job,
)
from app.services.notification import notify
from app.services.storage import StorageError, get_storage_provider

router = APIRouter()

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _is_patent_agent(user: User) -> bool:
    return "PATENT_AGENT" in {
        ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role
    }


async def _require_agent_or_admin(db: AsyncSession, user: User, patent) -> None:
    await _require_visible(db, user, patent)
    if _is_admin(user):
        return
    if patent.assigned_patent_agent_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin may manage documents for this application",
        )


@router.get("/{patent_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    result = await db.execute(
        select(Document).where(Document.patent_application_id == patent_id)
    )
    return result.scalars().all()


@router.get("/{patent_id}/documents/jobs", response_model=list[DocumentGenerationJobOut])
async def list_generation_jobs(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    result = await db.execute(
        select(DocumentGenerationJob)
        .where(DocumentGenerationJob.patent_application_id == patent_id)
        .order_by(DocumentGenerationJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{patent_id}/documents/jobs/{job_id}", response_model=DocumentGenerationJobOut)
async def get_generation_job(
    patent_id: int,
    job_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    job = await db.get(DocumentGenerationJob, job_id)
    if job is None or job.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation job not found")
    return job


@router.post("/{patent_id}/documents/generate", response_model=DocumentGenerationJobOut)
async def generate_documents(
    patent_id: int,
    payload: GenerateDocumentRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_agent_or_admin(db, user, patent)

    output_format = payload.output_format.upper()
    if output_format not in ("PDF", "DOCX"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "output_format must be PDF or DOCX")
    if output_format == "DOCX" and not _is_patent_agent(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the Patent Agent may select DOCX output"
        )

    document_type = payload.document_type or DOCUMENT_TYPES[0]
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown document_type: {document_type}")

    try:
        qv, outputs = await can_generate_documents(db, patent=patent)
    except DocumentGenerationNotAllowed as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from exc

    # Captured as primitives up front: a Failed run rolls back inside
    # run_generation_job, which expires every object in this session
    # (patent, user included) even though expire_on_commit=False only
    # covers commits. Touching an expired ORM attribute afterward without
    # an awaited reload crashes with MissingGreenlet — so from here on we
    # only touch the primitives, not user./patent. attributes, until any
    # branch needs a value that's still safe (patent.application_status
    # in the Completed branch below, which never goes through a rollback).
    triggered_by = user.id
    patent_id_val = patent.id

    job = await run_generation_job(
        db,
        patent=patent,
        qv=qv,
        outputs=outputs,
        document_type=document_type,
        output_format=output_format,
        triggered_by=triggered_by,
        storage=get_storage_provider(),
    )

    if job.status == "Completed":
        if patent.application_status == "Under Review":
            patent.application_status = "Draft Generated"
        await log_event(
            db, user_id=triggered_by, event_type="DOCUMENT_GENERATED",
            entity_type="patent_application", entity_id=patent_id_val,
            metadata={"job_id": job.id, "document_type": document_type, "output_format": output_format},
        )
        if patent.created_by:
            await notify(
                db, user_id=patent.created_by, notification_type="DraftGenerated",
                patent_application_id=patent_id_val,
            )
        await db.commit()
    else:
        await log_event(
            db, user_id=triggered_by, event_type="DOCUMENT_GENERATION_FAILED",
            entity_type="document_generation_job", entity_id=job.id,
            metadata={"error": job.error_message},
        )
        await db.commit()

    await db.refresh(job)
    return job


@router.post(
    "/{patent_id}/documents/jobs/{job_id}/retry", response_model=DocumentGenerationJobOut
)
async def retry_generation_job(
    patent_id: int,
    job_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Always creates a brand-new job (retried_from_job_id -> the original)
    that performs a full fresh generation — never a resume. The original
    failed job row is left exactly as-is for audit/history."""
    patent = await _get_patent_or_404(db, patent_id)
    await _require_agent_or_admin(db, user, patent)

    original = await db.get(DocumentGenerationJob, job_id)
    if original is None or original.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Generation job not found")
    if original.status != "Failed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a Failed job can be retried")

    # Re-derive document_type/output_format from the most recent Document
    # row for this patent, since the job itself doesn't store the request
    # payload — falls back to the V1 default type / PDF if none exists yet.
    result = await db.execute(
        select(Document).where(Document.patent_application_id == patent_id)
    )
    existing = result.scalars().first()
    document_type = existing.document_type if existing else DOCUMENT_TYPES[0]
    output_format = existing.output_format if existing else "PDF"
    if output_format == "DOCX" and not _is_patent_agent(user):
        output_format = "PDF"

    try:
        qv, outputs = await can_generate_documents(db, patent=patent)
    except DocumentGenerationNotAllowed as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from exc

    triggered_by = user.id
    original_id = original.id

    job = await run_generation_job(
        db,
        patent=patent,
        qv=qv,
        outputs=outputs,
        document_type=document_type,
        output_format=output_format,
        triggered_by=triggered_by,
        storage=get_storage_provider(),
        retried_from_job_id=original_id,
    )

    if job.status == "Completed" and patent.application_status == "Under Review":
        patent.application_status = "Draft Generated"
    await log_event(
        db, user_id=triggered_by,
        event_type="DOCUMENT_GENERATION_RETRIED",
        entity_type="document_generation_job", entity_id=job.id,
        metadata={"retried_from_job_id": original_id, "result": job.status},
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/{patent_id}/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_document_versions(
    patent_id: int,
    document_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    document = await db.get(Document, document_id)
    if document is None or document.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
    )
    return result.scalars().all()


async def _load_file(storage_key: str | None) -> bytes:
    if not storage_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No file stored for this document version")
    try:
        return await get_storage_provider().load(key=storage_key)
    except StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stored file could not be read: {exc}") from exc


def _response_for(storage_key: str, content: bytes) -> Response:
    ext = storage_key.rsplit(".", 1)[-1].lower()
    media_type = _MEDIA_TYPES.get(ext, "application/octet-stream")
    filename = storage_key.rsplit("/", 1)[-1]
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{patent_id}/documents/{document_id}/download")
async def download_latest_document(
    patent_id: int,
    document_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    document = await db.get(Document, document_id)
    if document is None or document.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    content = await _load_file(document.storage_key)
    return _response_for(document.storage_key, content)


@router.get("/{patent_id}/documents/versions/{version_id}/download")
async def download_document_version(
    patent_id: int,
    version_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    doc_version = await db.get(DocumentVersion, version_id)
    if doc_version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document version not found")
    document = await db.get(Document, doc_version.document_id)
    if document is None or document.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document version not found")

    content = await _load_file(doc_version.storage_key)
    return _response_for(doc_version.storage_key, content)
