from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PatentApplication, Team, TeamMember, User


async def is_team_member(db: AsyncSession, *, team_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
            TeamMember.membership_status == "Active",
        )
    )
    return result.scalar_one_or_none() is not None


async def member_team_ids(db: AsyncSession, *, user_id: int) -> list[int]:
    result = await db.execute(
        select(TeamMember.team_id).where(
            TeamMember.user_id == user_id, TeamMember.membership_status == "Active"
        )
    )
    return [row[0] for row in result.all()]


async def team_counts(db: AsyncSession, *, team_id: int) -> tuple[int, int]:
    member_count = (
        await db.execute(
            select(func.count(TeamMember.id)).where(
                TeamMember.team_id == team_id, TeamMember.membership_status == "Active"
            )
        )
    ).scalar_one()
    patent_count = (
        await db.execute(
            select(func.count(PatentApplication.id)).where(
                PatentApplication.team_id == team_id
            )
        )
    ).scalar_one()
    return member_count, patent_count


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()
