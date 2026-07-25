from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin


class Template(Base, IDMixin, TimestampMixin):
    """One shared, versioned template per document type. Editable ONLY by
    Admin or Super Admin (enforced at the application layer via
    require_permission, not here). document_type is intentionally NOT an
    enum tied to one patent office's form numbers — jurisdiction is TBD and
    the form set must stay configurable via this table's rows.

    NEW (closes open item #24): original_file_name + TimestampMixin were
    added here so the Templates admin UI can show a real upload history
    (name + date) per version, matching the File model's pattern. This is
    an additive migration (7bc9adf8f2ee -> next), safe on top of existing
    rows since both new columns are nullable / have a server default."""

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint(
            "document_type", "version_number", name="uq_templates_type_version"
        ),
    )

    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    original_file_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    edited_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
