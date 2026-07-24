from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin


class File(Base, IDMixin, TimestampMixin):
    """Supporting files uploaded against a patent application (drawings,
    prior art, etc.). Size/type limits (10MB max, executables blocked) are
    enforced at the application layer, not the database layer."""

    __tablename__ = "files"

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    storage_key: Mapped[str | None] = mapped_column(Text)
    original_file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))

    # BIGINT, not INT — future-proof even though the 10MB limit fits in INT
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
