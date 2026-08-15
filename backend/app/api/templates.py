"""Templates (NEW — closes open item #24 from the handover: no Templates
UI or real merging existed through Phase 8).

Admin/Super Admin can upload a .docx template per document_type. Per the
Template model's own docstring this is "one shared, versioned template
per document type" — uploading a new version auto-increments
version_number and, by default, activates it (deactivating whichever
version was previously active for that document_type, since only one
version can be "active" at a time per the model). Only Admin/Super Admin
may create, activate, or delete a template row, mirroring the model's own
comment about edit rights.

Deleting a template does not touch already-generated documents (those
are frozen DocumentVersion rows produced at generation time) — it only
removes this row and its stored file so it can no longer be selected as
the active template going forward.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.config import settings
from app.core.database import get_db
from app.models import Template, User
from app.schemas.collaboration import TemplateOut
from app.services.document_service import DOCUMENT_TYPES, validate_template_placeholders
from app.services.file_service import FileValidationError, validate_upload
from app.services.storage import StorageError, get_storage_provider

router = APIRouter()

# Only .docx is accepted — it's what docxtpl (Jinja-in-DOCX) merges
# against in document_service.py. Reject anything else at the door rather
# than fail obscurely at generation time.
_ALLOWED_TEMPLATE_EXTENSIONS = {".docx"}


async def _to_template_out(db: AsyncSession, t: Template) -> TemplateOut:
    editor_name = None
    if t.edited_by:
        editor = await db.get(User, t.edited_by)
        editor_name = editor.full_name if editor else None
    return TemplateOut(
        id=t.id,
        document_type=t.document_type,
        version_number=t.version_number,
        file_path=t.file_path,
        original_file_name=t.original_file_name,
        is_active=t.is_active,
        edited_by=t.edited_by,
        edited_by_name=editor_name,
    )


def _template_storage_key(*, document_type: str, version_number: int, filename: str) -> str:
    return f"templates/{document_type}/v{version_number}_{filename}"


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    document_type: str | None = Query(None),
    user: User = Depends(require_role("ADMIN", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Template).order_by(Template.document_type, Template.version_number.desc())
    if document_type:
        stmt = stmt.where(Template.document_type == document_type)
    result = await db.execute(stmt)
    return [await _to_template_out(db, t) for t in result.scalars().all()]


@router.get("/document-types", response_model=list[str])
async def list_document_types(
    user: User = Depends(require_role("ADMIN", "SUPER_ADMIN")),
):
    """The configurable set of document types a template can be uploaded
    for. Jurisdiction is still TBD (open item #1) so this is deliberately
    just the one type document_service.py knows about today; add more
    here once additional document types/forms are decided."""
    return list(DOCUMENT_TYPES)


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def upload_template(
    document_type: str,
    upload: UploadFile,
    activate: bool = Query(True, description="Make this the active version for document_type immediately"),
    user: User = Depends(require_role("ADMIN", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown document_type '{document_type}'. Valid values: {', '.join(DOCUMENT_TYPES)}",
        )

    filename = upload.filename or "template.docx"
    if not filename.lower().endswith(".docx"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Only .docx template files are accepted"
        )

    content = await upload.read()
    try:
        validate_upload(
            filename=filename,
            size_bytes=len(content),
            max_bytes=settings.max_upload_size_bytes,
            blocked_extensions=(),  # already restricted to .docx above
        )
    except FileValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    existing = await db.execute(
        select(Template.version_number)
        .where(Template.document_type == document_type)
        .order_by(Template.version_number.desc())
        .limit(1)
    )
    last_version = existing.scalar_one_or_none() or 0
    next_version = last_version + 1

    key = _template_storage_key(
        document_type=document_type, version_number=next_version, filename=filename
    )
    try:
        stored_key = await get_storage_provider().save(key=key, content=content)
    except StorageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to store template: {exc}") from exc

    if activate:
        await db.execute(
            Template.__table__.update()
            .where(Template.document_type == document_type, Template.is_active.is_(True))
            .values(is_active=False)
        )

    template = Template(
        document_type=document_type,
        version_number=next_version,
        file_path=stored_key,
        original_file_name=filename,
        is_active=activate,
        edited_by=user.id,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)

    validation = validate_template_placeholders(content)
    out = await _to_template_out(db, template)
    out.unknown_placeholders = validation.unknown_placeholders
    out.unused_known_placeholders = validation.unused_known_placeholders
    out.template_parse_error = validation.parse_error
    return out


@router.post("/{template_id}/activate", response_model=TemplateOut)
async def activate_template(
    template_id: int,
    user: User = Depends(require_role("ADMIN", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    template = await db.get(Template, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")

    await db.execute(
        Template.__table__.update()
        .where(Template.document_type == template.document_type, Template.is_active.is_(True))
        .values(is_active=False)
    )
    template.is_active = True
    template.edited_by = user.id
    await db.commit()
    await db.refresh(template)
    return await _to_template_out(db, template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    user: User = Depends(require_role("ADMIN", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    template = await db.get(Template, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")

    if template.file_path:
        await get_storage_provider().delete(key=template.file_path)
    await db.delete(template)
    await db.commit()
