from sqlalchemy import ForeignKey, String, UniqueConstraint, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import IDMixin, TimestampMixin


class Team(Base, IDMixin, TimestampMixin):
    """A standing group of collaborators. One team may file more than one
    patent application over time — this is NOT one-to-one with patents."""

    __tablename__ = "teams"

    team_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    team_status: Mapped[str] = mapped_column(String(30), default="ACTIVE")


class TeamMember(Base, IDMixin):
    """Membership of users within a team."""

    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),)

    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    added_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    membership_status: Mapped[str | None] = mapped_column(String(30))
