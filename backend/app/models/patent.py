from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin

# The full ~19-stage lifecycle from the spec (E8). Enforce valid transitions
# in the service layer (Phase 4), not just at the database layer.
APPLICATION_STATUSES = (
    "Draft", "Submitted", "Awaiting Patent Agent Acceptance", "Under Review",
    "Changes Requested", "Ready for Draft Generation", "Draft Generated",
    "Ready for Filing", "Filed", "Examination Requested", "FER Received",
    "FER Response Submitted", "Hearing Scheduled", "Granted", "Rejected",
    "Withdrawn", "Abandoned",
)


class PatentApplication(Base, IDMixin, TimestampMixin):
    """The central record of one invention's filing lifecycle."""

    __tablename__ = "patent_applications"

    # NOT unique — a team may own several patent applications
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.id"), nullable=False)

    invention_title: Mapped[str] = mapped_column(String(500), nullable=False)

    # Currently assigned agent — patent_assignments holds the full history
    assigned_patent_agent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id")
    )

    application_status: Mapped[str] = mapped_column(String(50), default="Draft")
    ai_status: Mapped[str | None] = mapped_column(String(30))
    questionnaire_status: Mapped[str | None] = mapped_column(String(30))
    document_status: Mapped[str | None] = mapped_column(String(30))
    filing_status: Mapped[str | None] = mapped_column(String(30))

    # Set only after manual filing with the relevant patent office
    # (jurisdiction TBD — see schema-reference.pdf note)
    official_application_number: Mapped[str | None] = mapped_column(String(50))
    filing_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))

    applicants: Mapped[list["Applicant"]] = relationship(back_populates="patent_application")  # noqa: F821
    inventors: Mapped[list["Inventor"]] = relationship(back_populates="patent_application")  # noqa: F821


class PatentAssignment(Base, IDMixin):
    """Complete history of Patent Agent assignment and reassignment."""

    __tablename__ = "patent_assignments"

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    patent_agent_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    assigned_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))

    # Pending / Assigned / Awaiting Acceptance / Accepted / Rejected / Reassigned
    assignment_status: Mapped[str | None] = mapped_column(String(30))

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    # Set only when an Admin/Super Admin force-reassigns a patent that
    # already has an ACCEPTED agent (open item #7 — see
    # app/services/patent_service.py's PRE_ASSIGNMENT_STATUSES /
    # perform_reassignment). Distinct from rejection: the agent didn't
    # decline, an admin removed them from an application they'd already
    # accepted.
    reassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reassignment_reason: Mapped[str | None] = mapped_column(Text)
