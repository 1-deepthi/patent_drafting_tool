from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models import PatentApplication, PatentAssignment, Role, User, UserRole
from app.services.team_service import member_team_ids

# Statuses that count as "actively assigned" for workload calculations —
# everything except the terminal end-states.
TERMINAL_STATUSES = {"Granted", "Rejected", "Withdrawn", "Abandoned"}

# Only these statuses may be edited (title change) or (re)assigned to an
# agent before that agent has accepted.
PRE_ASSIGNMENT_STATUSES = {"Draft", "Submitted", "Awaiting Patent Agent Acceptance"}

# Statuses eligible for a post-acceptance Admin reassignment (/reassign).
# Deliberately everything EXCEPT the pre-assignment states (those already
# go through /assign or /auto-assign, which don't need an admin override
# since no agent has accepted yet) and the terminal states (reassigning
# an agent onto a Granted/Rejected/Withdrawn/Abandoned application makes
# no sense — there's no active work left to hand off).
POST_ACCEPTANCE_REASSIGNMENT_STATUSES = (
    set(
        (
            "Under Review", "Changes Requested", "Ready for Draft Generation",
            "Draft Generated", "Ready for Filing", "Filed", "Examination Requested",
            "FER Received", "FER Response Submitted", "Hearing Scheduled",
        )
    )
    - TERMINAL_STATUSES
)


async def visible_patents_query(db: AsyncSession, *, user: User) -> Select:
    """Builds the base SELECT for patent_applications scoped to what this
    user is allowed to see. Per spec: Patent Agents see ONLY applications
    assigned to them; Admin/Super Admin see everything; Innovators see
    patents belonging to teams they're an active member of."""
    role_codes = {ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role}

    base = select(PatentApplication)

    if "SUPER_ADMIN" in role_codes or "ADMIN" in role_codes:
        return base

    if "PATENT_AGENT" in role_codes:
        return base.where(PatentApplication.assigned_patent_agent_id == user.id)

    # Innovator (default/fallback scoping)
    team_ids = await member_team_ids(db, user_id=user.id)
    if not team_ids:
        return base.where(PatentApplication.id.is_(None))  # empty result set
    return base.where(PatentApplication.team_id.in_(team_ids))


async def can_view_patent(db: AsyncSession, *, user: User, patent: PatentApplication) -> bool:
    role_codes = {ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role}
    if "SUPER_ADMIN" in role_codes or "ADMIN" in role_codes:
        return True
    if "PATENT_AGENT" in role_codes:
        return patent.assigned_patent_agent_id == user.id
    team_ids = await member_team_ids(db, user_id=user.id)
    return patent.team_id in team_ids


async def active_assignment_count(db: AsyncSession, *, agent_id: int) -> int:
    result = await db.execute(
        select(func.count(PatentApplication.id)).where(
            PatentApplication.assigned_patent_agent_id == agent_id,
            PatentApplication.application_status.not_in(TERMINAL_STATUSES),
        )
    )
    return result.scalar_one()


async def list_available_agents(db: AsyncSession) -> list[tuple[User, int]]:
    """Approved Patent Agents with their current active-assignment count,
    sorted lightest-workload first — used both for the Innovator's manual
    picker and for auto-assign."""
    result = await db.execute(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            Role.role_code == "PATENT_AGENT",
            UserRole.is_active.is_(True),
            User.account_status == "Approved",
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .distinct()
    )
    agents = result.scalars().all()
    counted = [(a, await active_assignment_count(db, agent_id=a.id)) for a in agents]
    counted.sort(key=lambda pair: pair[1])
    return counted


async def latest_assignment(db: AsyncSession, *, patent_application_id: int) -> PatentAssignment | None:
    result = await db.execute(
        select(PatentAssignment)
        .where(PatentAssignment.patent_application_id == patent_application_id)
        .order_by(PatentAssignment.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def perform_assignment(
    db: AsyncSession,
    *,
    patent: PatentApplication,
    agent_id: int,
    assigned_by_user_id: int,
) -> PatentAssignment:
    """Creates the assignment row and updates the patent's current-assignee
    fields. Does NOT commit — caller controls the transaction boundary."""
    from app.services.audit import log_event
    from app.services.notification import notify

    assignment = PatentAssignment(
        patent_application_id=patent.id,
        patent_agent_id=agent_id,
        assigned_by=assigned_by_user_id,
        assignment_status="Awaiting Acceptance",
    )
    db.add(assignment)

    patent.assigned_patent_agent_id = agent_id
    patent.application_status = "Awaiting Patent Agent Acceptance"

    await notify(
        db, user_id=agent_id, notification_type="Assigned", patent_application_id=patent.id
    )
    await log_event(
        db,
        user_id=assigned_by_user_id,
        event_type="PATENT_AGENT_ASSIGNED",
        entity_type="patent_application",
        entity_id=patent.id,
        metadata={"agent_id": agent_id},
    )
    await db.flush()
    return assignment


async def perform_reassignment(
    db: AsyncSession,
    *,
    patent: PatentApplication,
    new_agent_id: int,
    reassigned_by_user_id: int,
    reason: str,
) -> PatentAssignment:
    """Admin/Super Admin override of an already-ACCEPTED assignment (open
    item #7). Per spec item 12, this still can't hand the admin the power
    to accept/reject on an agent's behalf — the new agent goes back
    through the normal assignment/accept or assignment/reject endpoints
    like any other assignment, they just start from an admin's pick
    instead of the pool. Does NOT commit — caller controls the
    transaction boundary."""
    from app.services.audit import log_event
    from app.services.notification import notify

    previous_agent_id = patent.assigned_patent_agent_id
    now = datetime.now(timezone.utc)

    previous = await latest_assignment(db, patent_application_id=patent.id)
    if previous is not None and previous.assignment_status == "Accepted":
        previous.assignment_status = "Reassigned"
        previous.reassigned_at = now
        previous.reassignment_reason = reason

    assignment = PatentAssignment(
        patent_application_id=patent.id,
        patent_agent_id=new_agent_id,
        assigned_by=reassigned_by_user_id,
        assignment_status="Awaiting Acceptance",
    )
    db.add(assignment)

    patent.assigned_patent_agent_id = new_agent_id
    patent.application_status = "Awaiting Patent Agent Acceptance"

    if previous_agent_id is not None:
        await notify(
            db,
            user_id=previous_agent_id,
            notification_type="Reassigned",
            patent_application_id=patent.id,
        )
    await notify(
        db, user_id=new_agent_id, notification_type="Assigned", patent_application_id=patent.id
    )
    await log_event(
        db,
        user_id=reassigned_by_user_id,
        event_type="PATENT_AGENT_REASSIGNED",
        entity_type="patent_application",
        entity_id=patent.id,
        metadata={
            "previous_agent_id": previous_agent_id,
            "new_agent_id": new_agent_id,
            "reason": reason,
        },
    )
    await db.flush()
    return assignment
