from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin


class Template(Base, IDMixin):
    """One shared, versioned template per document type. Editable ONLY by
    Admin or Super Admin (enforced at the application layer via
    require_permission, not here). document_type is intentionally NOT an
    enum tied to one patent office's form numbers — jurisdiction is TBD and
    the form set must stay configurable via this table's rows."""

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint(
            "document_type", "version_number", name="uq_templates_type_version"
        ),
    )

    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    edited_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
