from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin


class Document(Base, IDMixin):
    """One generated document instance per patent application per document
    type. Only ever created by finalizing a successfully COMPLETED
    document_generation_job — never written directly by a synchronous
    request."""

    __tablename__ = "documents"

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    template_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("templates.id"))
    document_type: Mapped[str | None] = mapped_column(String(50))

    # PDF is default for every role; DOCX selectable only by the Patent Agent
    output_format: Mapped[str] = mapped_column(String(10), default="PDF")

    # DRAFT / None — removed once the application is approved
    watermark_status: Mapped[str | None] = mapped_column(String(20))

    # Must be the assigned Patent Agent
    generated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_key: Mapped[str | None] = mapped_column(Text)


class DocumentVersion(Base, IDMixin):
    """Every regeneration, kept with a diff summary — version comparison is
    a V1 requirement, not optional."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_doc_version"),
    )

    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("documents.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)  # each version is its own stored file
    generated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentGenerationJob(Base, IDMixin, TimestampMixin):
    """Tracks each background generation run triggered by a Patent Agent
    clicking 'Generate Documents'. Files are written to a temporary,
    job-specific R2 location and only linked into documents/
    document_versions once the whole batch completes successfully — a
    partially generated batch is never treated as complete. Retry always
    creates a NEW job (self-referential retried_from_job_id) that performs
    a full fresh generation, never a resume; the original failed job is
    preserved for audit/history and never overwritten."""

    __tablename__ = "document_generation_jobs"

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    # Queued / Processing / Completed / Failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Queued")

    triggered_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)

    retried_from_job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document_generation_jobs.id")
    )

    error_message: Mapped[str | None] = mapped_column(Text)

    # R2 prefix holding this job's in-flight files before finalization
    temporary_storage_prefix: Mapped[str | None] = mapped_column(String(500))

    # Pending / Cleaned / Failed — tracks deletion of temp files after a
    # failed job's retention period
    cleanup_status: Mapped[str | None] = mapped_column(String(20))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
