from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import IDMixin


class Role(Base, IDMixin):
    """Seed rows: SUPER_ADMIN, ADMIN, PATENT_AGENT, INNOVATOR."""

    __tablename__ = "roles"

    role_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    role_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))


class Permission(Base, IDMixin):
    """Module-level action grants, e.g. PATENT_EDIT, TEMPLATE_UPLOAD."""

    __tablename__ = "permissions"

    permission_name: Mapped[str] = mapped_column(String(150))
    permission_code: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    module_name: Mapped[str | None] = mapped_column(String(100))
    # View / Create / Edit / Delete / Generate / Download
    action: Mapped[str | None] = mapped_column(String(30))


class UserRole(Base, IDMixin):
    """Assigns one or more roles to a user."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id"), nullable=False)
    assigned_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revoked_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(foreign_keys=[user_id], back_populates="user_roles")  # noqa: F821
    role: Mapped["Role"] = relationship(foreign_keys=[role_id])


class RolePermission(Base, IDMixin):
    """Backs the V1 Role & Permission management dashboard."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
    )

    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("permissions.id"), nullable=False
    )
    assigned_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
