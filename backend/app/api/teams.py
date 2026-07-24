"""Teams — standing collaboration groups. A team may file many patent
applications over time (NOT one-to-one with patents). Team creation is an
Innovator action per spec; Admin/Super Admin have read-only oversight of
all teams but do not create them here.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_role
from app.core.database import get_db
from app.models import Team, TeamMember, User
from app.schemas.teams import (
    AddTeamMemberRequest,
    TeamCreate,
    TeamDetailOut,
    TeamMemberOut,
    TeamOut,
    TeamUpdate,
)
from app.services.team_service import get_user_by_email, is_team_member, member_team_ids, team_counts

router = APIRouter()


def _is_admin(user: User) -> bool:
    codes = {ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role}
    return bool(codes & {"SUPER_ADMIN", "ADMIN"})


async def _team_to_out(db: AsyncSession, team: Team) -> TeamOut:
    member_count, patent_count = await team_counts(db, team_id=team.id)
    return TeamOut(
        id=team.id,
        team_name=team.team_name,
        team_status=team.team_status,
        created_by=team.created_by,
        created_at=team.created_at,
        member_count=member_count,
        patent_count=patent_count,
    )


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate,
    user: User = Depends(require_role("INNOVATOR")),
    db: AsyncSession = Depends(get_db),
):
    team = Team(team_name=payload.team_name, created_by=user.id, team_status="ACTIVE")
    db.add(team)
    await db.flush()
    db.add(TeamMember(team_id=team.id, user_id=user.id, added_by=user.id, membership_status="Active"))
    await db.commit()
    return await _team_to_out(db, team)


@router.get("", response_model=list[TeamOut])
async def list_teams(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if _is_admin(user):
        result = await db.execute(select(Team).order_by(Team.id))
        teams = result.scalars().all()
    else:
        team_ids = await member_team_ids(db, user_id=user.id)
        if not team_ids:
            return []
        result = await db.execute(select(Team).where(Team.id.in_(team_ids)).order_by(Team.id))
        teams = result.scalars().all()

    return [await _team_to_out(db, t) for t in teams]


async def _get_team_or_404(db: AsyncSession, team_id: int) -> Team:
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return team


async def _require_team_access(db: AsyncSession, user: User, team: Team) -> None:
    if _is_admin(user):
        return
    if not await is_team_member(db, team_id=team.id, user_id=user.id):
        # 404, not 403 — don't confirm the team exists to non-members
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")


@router.get("/{team_id}", response_model=TeamDetailOut)
async def get_team(
    team_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    team = await _get_team_or_404(db, team_id)
    await _require_team_access(db, user, team)

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.membership_status == "Active"
        )
    )
    members_rows = result.scalars().all()

    members: list[TeamMemberOut] = []
    for m in members_rows:
        member_user = await db.get(User, m.user_id)
        members.append(
            TeamMemberOut(
                id=m.id,
                user_id=m.user_id,
                email=member_user.email if member_user else "",
                full_name=member_user.full_name if member_user else "",
                membership_status=m.membership_status,
                added_by=m.added_by,
            )
        )

    base = await _team_to_out(db, team)
    return TeamDetailOut(**base.model_dump(), members=members)


def _require_team_owner_or_admin(user: User, team: Team) -> None:
    if _is_admin(user):
        return
    if team.created_by != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the team creator or an Admin can do this"
        )


@router.patch("/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: int,
    payload: TeamUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    team = await _get_team_or_404(db, team_id)
    _require_team_owner_or_admin(user, team)

    if payload.team_name is not None:
        team.team_name = payload.team_name
    if payload.team_status is not None:
        team.team_status = payload.team_status

    await db.commit()
    return await _team_to_out(db, team)


@router.post("/{team_id}/members", response_model=TeamMemberOut, status_code=status.HTTP_201_CREATED)
async def add_team_member(
    team_id: int,
    payload: AddTeamMemberRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    team = await _get_team_or_404(db, team_id)
    _require_team_owner_or_admin(user, team)

    target = await get_user_by_email(db, payload.email)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No user found with that email")
    if target.account_status != "Approved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User must be an approved account")

    existing = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == target.id)
    )
    row = existing.scalar_one_or_none()

    if row is not None and row.membership_status == "Active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User is already a team member")

    if row is not None:
        row.membership_status = "Active"
        row.added_by = user.id
    else:
        row = TeamMember(team_id=team_id, user_id=target.id, added_by=user.id, membership_status="Active")
        db.add(row)

    await db.commit()
    await db.refresh(row)
    return TeamMemberOut(
        id=row.id,
        user_id=target.id,
        email=target.email,
        full_name=target.full_name,
        membership_status=row.membership_status,
        added_by=row.added_by,
    )


@router.delete("/{team_id}/members/{user_id}")
async def remove_team_member(
    team_id: int,
    user_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    team = await _get_team_or_404(db, team_id)
    _require_team_owner_or_admin(user, team)

    if user_id == team.created_by:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot remove the team creator from the team"
        )

    result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None or row.membership_status != "Active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Active membership not found")

    row.membership_status = "Removed"
    await db.commit()
    return {"detail": "Member removed"}
