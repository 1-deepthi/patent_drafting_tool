from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin


class Comment(Base, IDMixin):
    """Permanent, never-deleted discussion thread per patent application —
    forms the collaboration audit trail. No update/delete endpoint should
    ever be built against this table."""

    __tablename__ = "comments"

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(Base, IDMixin):
    """Generic, TYPE-DRIVEN notifications — deliberately no stored message
    text. The frontend renders text from a fixed template per
    notification_type, joining to the linked patent application for
    specifics (e.g. the invention title) at render time."""

    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    patent_application_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id")
    )
    # Submitted / Assigned / Accepted / Rejected / Reassigned /
    # ChangeRequested / DraftGenerated / FilingRecorded / Granted
    notification_type: Mapped[str | None] = mapped_column(String(50))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base, IDMixin):
    """Permanent record of patent, document, and admin activity. Deliberately
    EXCLUDES login/logout events — those are tracked only as simple state
    fields on users.last_login_at / last_logout_at, never as audit rows."""

    __tablename__ = "audit_logs"

    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    event_type: Mapped[str | None] = mapped_column(String(80))
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    log_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CalendarEvent(Base, IDMixin):
    """Deadlines, examinations, hearings, and reminders shown on the
    calendar view."""

    __tablename__ = "calendar_events"

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    # Filing Deadline / Examination / Hearing / Reminder
    event_type: Mapped[str | None] = mapped_column(String(50))
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))


class ReportPermission(Base, IDMixin):
    """Controls which report types a role (e.g. Innovator, post-grant) may
    download. Role-scoped, not per-user — set only by the Super Admin."""

    __tablename__ = "report_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "report_type", name="uq_report_permissions_role_type"),
    )

    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(80), nullable=False)
    can_download: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
