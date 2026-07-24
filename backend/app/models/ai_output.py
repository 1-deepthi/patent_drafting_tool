from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin


class AIOutput(Base, IDMixin, TimestampMixin):
    """Gemini-generated content, produced SECTION BY SECTION so that any
    single section can be regenerated independently without touching the
    others. ai_response is TEXT (PostgreSQL) — never LONGTEXT, which is a
    MySQL-only type and would be invalid here."""

    __tablename__ = "ai_outputs"
    __table_args__ = (
        UniqueConstraint(
            "questionnaire_version_id", "section_type", "version_number",
            name="uq_ai_outputs_qv_section_version",
        ),
    )

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    questionnaire_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questionnaire_versions.id"), nullable=False
    )

    # CLAIMS / ABSTRACT / DESCRIPTION / FULL_DRAFT / etc.
    section_type: Mapped[str] = mapped_column(String(30), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    ai_provider: Mapped[str | None] = mapped_column(String(100))
    ai_model: Mapped[str | None] = mapped_column(String(150))
    prompt_text: Mapped[str | None] = mapped_column(Text)
    ai_response: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str | None] = mapped_column(String(30))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
