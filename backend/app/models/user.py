from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin


class User(Base, IDMixin, TimestampMixin):
    """Master record for every registered user — Innovator, Patent Agent,
    Admin, or Super Admin. Authentication is Google OAuth 2.0 only: there
    are NO password fields anywhere on this model, by design."""

    __tablename__ = "users"

    google_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(20))
    profile_picture: Mapped[str | None] = mapped_column(String)
    designation: Mapped[str | None] = mapped_column(String(150))
    organization: Mapped[str | None] = mapped_column(String(200))

    # Pending / Approved / Rejected / Suspended
    account_status: Mapped[str] = mapped_column(String(30), nullable=False, default="Pending")

    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # State fields only — no login/logout audit_logs entries are ever generated
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_logout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user_roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", foreign_keys="UserRole.user_id"
    )
