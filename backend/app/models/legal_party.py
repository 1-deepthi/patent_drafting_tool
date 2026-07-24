from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    BigInteger,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin


class Applicant(Base, IDMixin, TimestampMixin):
    """The legal person or entity applying for the patent — distinct from
    Team, which governs platform collaboration/access, not legal filing
    identity. One patent application may have multiple applicants (joint
    filing), but at most one may be marked primary."""

    __tablename__ = "applicants"
    __table_args__ = (
        # Partial unique index: at most one row per patent_application_id
        # where is_primary is true. This is what actually enforces "at most
        # one primary applicant per patent" — a plain column constraint
        # can't express this, only a partial index can.
        Index(
            "uq_applicants_one_primary_per_patent",
            "patent_application_id",
            unique=True,
            postgresql_where=text("is_primary = true"),
        ),
        # Mirrors Inventor.inventor_order — display_order is a property of
        # THIS filing's applicant list, not of the applicant record itself.
        UniqueConstraint(
            "patent_application_id", "display_order", name="uq_applicants_patent_order"
        ),
    )

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    # Individual / Startup / Company / University
    applicant_type: Mapped[str] = mapped_column(String(30), nullable=False)
    full_name_or_org_name: Mapped[str] = mapped_column(String(300), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Added Phase 5 (handover v2 open item #5) — mirrors Inventor.inventor_order.
    # is_primary still governs which applicant is legally primary; display_order
    # only controls list/document display sequence and is independent of it.
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    patent_application: Mapped["PatentApplication"] = relationship(back_populates="applicants")  # noqa: F821


class Inventor(Base, IDMixin, TimestampMixin):
    """Legal persons named as inventors on the patent. Patent-specific —
    inventor_order is a property of THIS filing, not of the person. A
    person can be an inventor on many patents (person <-> patent is
    many-to-many via this table), and user_id is nullable because an
    inventor may be legally named without ever holding a platform account."""

    __tablename__ = "inventors"
    __table_args__ = (
        UniqueConstraint(
            "patent_application_id", "inventor_order", name="uq_inventors_patent_order"
        ),
    )

    patent_application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patent_applications.id"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    inventor_order: Mapped[int] = mapped_column(Integer, nullable=False)

    patent_application: Mapped["PatentApplication"] = relationship(back_populates="inventors")  # noqa: F821
