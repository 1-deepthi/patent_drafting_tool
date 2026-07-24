from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class IDMixin:
    """BIGSERIAL primary key, shared by every table in the schema."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class TimestampMixin:
    """created_at / updated_at, present on every table unless noted otherwise
    in schema-reference.pdf."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
