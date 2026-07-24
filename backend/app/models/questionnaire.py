from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint, BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin

# Shared free-text fields, same on questionnaires and questionnaire_versions
QUESTIONNAIRE_TEXT_FIELDS = (
    "problem_statement", "proposed_solution", "novelty_description",
    "technical_description", "advantages", "prior_art", "keywords",
)


class Questionnaire(Base, IDMixin, TimestampMixin):
    """Guided, multi-step invention questionnaire. NOTE: Basic Information
    (title/applicants/inventors) is captured on patent_applications /
    applicants / inventors, NOT here — this table holds only the invention
    content (About the Invention, Your Solution, Technical Details)."""

    __tablename__ = "questionnaires"

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), unique=True, nullable=False
    )
    questionnaire_status: Mapped[str | None] = mapped_column(String(30))
    completion_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    # Software / Mechanical / Electronics / Biotech / Chemistry — drives
    # frontend branching for Technical Details; not a DB-driven form builder
    invention_type: Mapped[str | None] = mapped_column(String(30))

    problem_statement: Mapped[str | None] = mapped_column(Text)
    proposed_solution: Mapped[str | None] = mapped_column(Text)
    novelty_description: Mapped[str | None] = mapped_column(Text)
    technical_description: Mapped[str | None] = mapped_column(Text)
    advantages: Mapped[str | None] = mapped_column(Text)
    prior_art: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)
    has_existing_drawings: Mapped[bool | None] = mapped_column(Boolean)


class QuestionnaireVersion(Base, IDMixin):
    """Full snapshot taken at each edit/resubmission cycle."""

    __tablename__ = "questionnaire_versions"
    __table_args__ = (
        UniqueConstraint(
            "questionnaire_id", "version_number", name="uq_questionnaire_versions_q_version"
        ),
    )

    questionnaire_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("questionnaires.id"), nullable=False
    )
    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_status: Mapped[str | None] = mapped_column(String(30))

    # Same field snapshot as Questionnaire
    invention_type: Mapped[str | None] = mapped_column(String(30))
    problem_statement: Mapped[str | None] = mapped_column(Text)
    proposed_solution: Mapped[str | None] = mapped_column(Text)
    novelty_description: Mapped[str | None] = mapped_column(Text)
    technical_description: Mapped[str | None] = mapped_column(Text)
    advantages: Mapped[str | None] = mapped_column(Text)
    prior_art: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)

    change_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
