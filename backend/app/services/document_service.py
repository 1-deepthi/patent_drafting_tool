"""Phase 7 — workflow items 9/10 (Generate Documents job + tracking).

Assembles the patent application's AI-drafted sections (Phase 6's
AIOutput rows) plus a Template row into an actual filed-style document
(DOCX, optionally converted to PDF), and tracks the run as a
DocumentGenerationJob exactly per the schema's own docstring: runs
synchronously inside the request today (Celery/Redis explicitly deferred
project-wide, same as Phase 6's AI generation — see config.py), a
partially generated batch is never treated as complete, and retrying
always creates a brand NEW job rather than resuming the old one.

DOCUMENT_TYPES is deliberately a single jurisdiction-agnostic type today
(open item #1 — jurisdiction still undecided), mirroring Phase 6's
SECTION_TYPES choice. Admin/Super Admin can define additional Template
rows for other document_type values later via app/api/templates.py; this
service only assumes a Template *may* exist for a type, and falls back to
a plain generated layout if none is active yet.

UPDATE (closes open item #24): real template merging is now wired in.
An active Template's stored .docx is merged via docxtpl (Jinja-in-DOCX)
against {{ TITLE }}, {{ ABSTRACT }}, {{ BACKGROUND }}, {{ SUMMARY }},
{{ DESCRIPTION }}, {{ CLAIMS }}, and {{ WATERMARK_TEXT }} placeholders —
the admin controls layout/letterhead/headers-footers entirely from the
uploaded .docx; this service only fills in values. Falls back to the
previous plain python-docx layout if no Template is active, or if the
merge itself fails (e.g. a malformed template) — a bad template must
never take document generation down.
"""

import io
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor
from docxtpl import DocxTemplate
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    AIOutput,
    Document,
    DocumentGenerationJob,
    DocumentVersion,
    PatentApplication,
    QuestionnaireVersion,
    Template,
)
from app.services.draft_service import (
    SECTION_TYPES,
    latest_completed_questionnaire_version,
    latest_outputs_by_section,
)
from app.services.storage import StorageError, StorageProvider

# One shared type for V1 — see module docstring re: open item #1.
DOCUMENT_TYPES: tuple[str, ...] = ("PATENT_APPLICATION",)

SECTION_LABELS: dict[str, str] = {
    "ABSTRACT": "Abstract",
    "BACKGROUND": "Background",
    "SUMMARY": "Summary",
    "DESCRIPTION": "Detailed Description",
    "CLAIMS": "Claims",
}

# application_status values that count as "already approved" for
# watermarking purposes — mirrors the free-text 19-stage status column;
# only Granted is unambiguously past the point a DRAFT watermark still
# applies. Flag if more statuses (e.g. Filed) should also drop it.
_NO_WATERMARK_STATUSES = {"Granted"}


class DocumentGenerationNotAllowed(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def storage_key_for(*, patent_application_id: int, job_id: int, output_format: str) -> str:
    ext = "pdf" if output_format == "PDF" else "docx"
    return f"documents/{patent_application_id}/job-{job_id}.{ext}"


async def can_generate_documents(
    db: AsyncSession, *, patent: PatentApplication
) -> tuple[QuestionnaireVersion, dict[str, AIOutput]]:
    """Raises DocumentGenerationNotAllowed with a human reason, or returns
    (questionnaire_version, {section_type: latest_completed_AIOutput})
    for every required section.

    Gate (new Phase 7 decision — flag if wrong): allowed once the
    assigned Patent Agent has accepted (application_status in {"Under
    Review", "Draft Generated"} — the latter allows regenerating after an
    earlier run) AND every one of Phase 6's 5 sections has at least one
    Completed AIOutput for the latest submitted questionnaire version.
    """
    if patent.application_status not in ("Under Review", "Draft Generated"):
        raise DocumentGenerationNotAllowed(
            "Document generation is only available once the assigned Patent Agent has "
            f"accepted the application and AI drafting is underway (current status: "
            f"{patent.application_status})"
        )

    qv = await latest_completed_questionnaire_version(
        db, patent_application_id=patent.id
    )
    if qv is None:
        raise DocumentGenerationNotAllowed("No submitted questionnaire found for this application yet")

    latest_by_section = await latest_outputs_by_section(db, questionnaire_version_id=qv.id)
    missing = [
        SECTION_LABELS[st]
        for st in SECTION_TYPES
        if latest_by_section.get(st) is None or latest_by_section[st].processing_status != "Completed"
    ]
    if missing:
        raise DocumentGenerationNotAllowed(
            "AI drafting must be completed for every section before generating documents. "
            f"Missing or not-yet-completed: {', '.join(missing)}"
        )
    return qv, latest_by_section


async def _active_template(db: AsyncSession, *, document_type: str) -> Template | None:
    result = await db.execute(
        select(Template)
        .where(Template.document_type == document_type, Template.is_active.is_(True))
        .order_by(Template.version_number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _merge_with_template(
    *,
    template_bytes: bytes,
    patent: PatentApplication,
    outputs: dict[str, AIOutput],
    watermark: bool,
) -> bytes:
    """Real template merge via docxtpl. The uploaded .docx owns all
    layout/letterhead/headers-footers; we only fill in the Jinja
    placeholders below. Raises on a malformed template — caller decides
    whether to fall back."""
    tpl = DocxTemplate(io.BytesIO(template_bytes))
    context = {
        "TITLE": patent.invention_title or "Untitled Invention",
        "WATERMARK_TEXT": "DRAFT — NOT FOR FILING" if watermark else "",
    }
    for section_type in SECTION_TYPES:
        context[section_type] = (outputs[section_type].ai_response or "").strip()
    tpl.render(context)
    buffer = io.BytesIO()
    tpl.save(buffer)
    buffer.seek(0)
    return buffer.read()


def _build_plain_docx_bytes(
    *,
    patent: PatentApplication,
    outputs: dict[str, AIOutput],
    watermark: bool,
) -> bytes:
    """The original plain, cleanly formatted layout — used whenever no
    Template is active for this document_type, or a template merge fails."""
    doc = DocxDocument()

    if watermark:
        banner = doc.add_paragraph()
        banner.alignment = 1  # center
        run = banner.add_run("DRAFT — NOT FOR FILING")
        run.bold = True
        run.font.size = Pt(14)
        run.font.color.rgb = RGBColor(0xC0, 0x30, 0x30)

    title = doc.add_heading(patent.invention_title or "Untitled Invention", level=0)
    title.alignment = 1

    for section_type in SECTION_TYPES:
        output = outputs[section_type]
        doc.add_heading(SECTION_LABELS[section_type], level=1)
        body = output.ai_response or ""
        for paragraph_text in body.split("\n\n"):
            if paragraph_text.strip():
                doc.add_paragraph(paragraph_text.strip())

    buffer = tempfile.SpooledTemporaryFile()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()


def build_docx_bytes(
    *,
    patent: PatentApplication,
    outputs: dict[str, AIOutput],
    watermark: bool,
    template_bytes: bytes | None = None,
) -> bytes:
    """Public entry point. Merges against template_bytes (the active
    Template's stored .docx, already loaded by the caller) when provided;
    falls back to the plain layout if no template is active OR if the
    merge raises — a bad/malformed template must never block document
    generation outright."""
    if template_bytes is not None:
        try:
            return _merge_with_template(
                template_bytes=template_bytes, patent=patent, outputs=outputs, watermark=watermark
            )
        except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
            logger.warning(
                "Template merge failed for patent {}, falling back to plain layout: {}",
                patent.id, exc,
            )
    return _build_plain_docx_bytes(patent=patent, outputs=outputs, watermark=watermark)


def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    """Shells out to headless LibreOffice for DOCX -> PDF conversion, per
    the tech stack's documented choice. Confirmed available and
    live-verified in this sandbox (unlike Gemini/R2, which aren't reachable
    here) — see the Phase 7 verification notes in the handover."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        docx_path = tmp_path / "input.docx"
        docx_path.write_bytes(docx_bytes)

        result = subprocess.run(
            [
                settings.libreoffice_binary,
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path),
                str(docx_path),
            ],
            capture_output=True,
            timeout=settings.libreoffice_timeout_seconds,
        )
        pdf_path = tmp_path / "input.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            raise RuntimeError(
                f"LibreOffice conversion failed (exit {result.returncode}): "
                f"{result.stderr.decode(errors='replace')[:500]}"
            )
        return pdf_path.read_bytes()


async def _next_document_version_number(db: AsyncSession, *, document_id: int) -> int:
    result = await db.execute(
        select(DocumentVersion.version_number)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    return (latest or 0) + 1


async def run_generation_job(
    db: AsyncSession,
    *,
    patent: PatentApplication,
    qv: QuestionnaireVersion,
    outputs: dict[str, AIOutput],
    document_type: str,
    output_format: str,
    triggered_by: int,
    storage: StorageProvider,
    retried_from_job_id: int | None = None,
) -> DocumentGenerationJob:
    """Creates and drives one DocumentGenerationJob start-to-finish, given
    an already-validated (qv, outputs) pair from can_generate_documents —
    the caller (app/api/documents.py) checks eligibility and raises a 400
    BEFORE any job row is created, same as ai.generate_draft does for AI
    drafting. Per the model's own docstring, a job is either Completed
    (Document + DocumentVersion rows exist and are safe to read) or Failed
    (nothing is linked in) — never left half-done."""
    # Committed immediately, separately from the work below, so a failed
    # run still leaves a real, queryable job row — never rolled away with
    # whatever else failed. This is what "the original failed job is
    # preserved for audit/history and never overwritten" requires.
    job = DocumentGenerationJob(
        patent_application_id=patent.id,
        status="Processing",
        triggered_by=triggered_by,
        retried_from_job_id=retried_from_job_id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    try:
        watermark = patent.application_status not in _NO_WATERMARK_STATUSES

        active_template = await _active_template(db, document_type=document_type)
        template_bytes: bytes | None = None
        if active_template is not None and active_template.file_path:
            try:
                template_bytes = await storage.load(key=active_template.file_path)
            except StorageError as exc:
                logger.warning(
                    "Could not load active template {} for patent {}, falling back to "
                    "plain layout: {}", active_template.id, patent.id, exc,
                )

        docx_bytes = build_docx_bytes(
            patent=patent, outputs=outputs, watermark=watermark, template_bytes=template_bytes
        )

        if output_format == "PDF":
            file_bytes = await _to_thread_convert(docx_bytes)
        else:
            file_bytes = docx_bytes

        key = storage_key_for(
            patent_application_id=patent.id, job_id=job.id, output_format=output_format
        )
        job.temporary_storage_prefix = f"documents/{patent.id}/job-{job.id}"
        stored_key = await storage.save(key=key, content=file_bytes)

        result = await db.execute(
            select(Document).where(
                Document.patent_application_id == patent.id,
                Document.document_type == document_type,
            )
        )
        document = result.scalar_one_or_none()

        if document is None:
            document = Document(
                patent_application_id=patent.id,
                template_id=active_template.id if active_template else None,
                document_type=document_type,
            )
            db.add(document)
            await db.flush()

        version_number = await _next_document_version_number(db, document_id=document.id)
        section_summary = ", ".join(
            f"{SECTION_LABELS[st]} v{outputs[st].version_number}" for st in SECTION_TYPES
        )
        change_summary = (
            f"Generated from questionnaire v{qv.version_number}; sections: {section_summary}"
        )
        if retried_from_job_id:
            change_summary = f"[Retry of job {retried_from_job_id}] " + change_summary

        doc_version = DocumentVersion(
            document_id=document.id,
            version_number=version_number,
            change_summary=change_summary,
            storage_key=stored_key,
            generated_by=triggered_by,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(doc_version)

        document.template_id = template.id if template else document.template_id
        document.output_format = output_format
        document.watermark_status = "DRAFT" if watermark else None
        document.generated_by = triggered_by
        document.generated_at = doc_version.generated_at
        document.storage_key = stored_key

        job.status = "Completed"
        job.completed_at = datetime.now(timezone.utc)
        job.cleanup_status = "Cleaned"  # nothing left in a temp-only location to clean up

        await db.commit()
        await db.refresh(job)
        return job

    except (StorageError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        await db.rollback()  # discards any half-added Document/DocumentVersion rows only
        job.status = "Failed"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = str(exc)
        job.cleanup_status = "Pending"  # any partial file left in storage isn't cleaned up yet
        await db.commit()
        await db.refresh(job)
        return job


async def _to_thread_convert(docx_bytes: bytes) -> bytes:
    import asyncio

    return await asyncio.to_thread(convert_docx_to_pdf, docx_bytes)
