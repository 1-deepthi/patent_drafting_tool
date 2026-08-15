"""Patent Applications — the central lifecycle record. Visibility is
strictly scoped per spec: Patent Agents see ONLY applications assigned to
them; Admin/Super Admin see everything; Innovators see patents belonging
to teams they're an active member of. Admin/Super Admin can assign or
reassign an agent BEFORE that agent accepts, but per spec item 12 they can
never override the agent's own Accept/Reject decision — only the assigned
agent may call the accept/reject endpoints.

Post-acceptance reassignment (open item #7, closed here): once an agent
has accepted, /assign and /auto-assign refuse to touch the patent (see
PRE_ASSIGNMENT_STATUSES). An Admin/Super Admin who needs to pull a patent
off an agent who already accepted it — the agent went unresponsive, left
the firm, whatever the real-world reason — uses /reassign instead. It
still respects item 12: the new agent lands in "Awaiting Patent Agent
Acceptance" and has to accept or reject like any other assignment, an
admin can't accept on their behalf.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_active_user, require_role
from app.core.database import get_db
from app.models import PatentApplication, User, UserRole
from app.schemas.patents import (
    AssignAgentRequest,
    AvailableAgentOut,
    PatentCreate,
    PatentOut,
    PatentUpdate,
    ReassignAgentRequest,
    RejectAssignmentRequest,
)
from app.services.audit import log_event
from app.services.notification import notify
from app.services.patent_service import (
    POST_ACCEPTANCE_REASSIGNMENT_STATUSES,
    PRE_ASSIGNMENT_STATUSES,
    can_view_patent,
    latest_assignment,
    list_available_agents,
    perform_assignment,
    perform_reassignment,
    visible_patents_query,
)
from app.services.questionnaire_service import basic_info_complete
from app.services.team_service import is_team_member

router = APIRouter()


def _is_admin(user: User) -> bool:
    codes = {ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role}
    return bool(codes & {"SUPER_ADMIN", "ADMIN"})


async def _get_patent_or_404(db: AsyncSession, patent_id: int) -> PatentApplication:
    patent = await db.get(PatentApplication, patent_id)
    if patent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent application not found")
    return patent


async def _require_visible(db: AsyncSession, user: User, patent: PatentApplication) -> None:
    if not await can_view_patent(db, user=user, patent=patent):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent application not found")


async def _load_approved_agent_or_400(db: AsyncSession, agent_id: int) -> User:
    agent_result = await db.execute(
        select(User)
        .where(User.id == agent_id)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
    )
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    agent_role_codes = {ur.role.role_code for ur in agent.user_roles if ur.is_active and ur.role}
    if "PATENT_AGENT" not in agent_role_codes or agent.account_status != "Approved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That user is not an approved Patent Agent")
    return agent


@router.post("", response_model=PatentOut, status_code=status.HTTP_201_CREATED)
async def create_patent(
    payload: PatentCreate,
    user: User = Depends(require_role("INNOVATOR")),
    db: AsyncSession = Depends(get_db),
):
    if not await is_team_member(db, team_id=payload.team_id, user_id=user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")

    patent = PatentApplication(
        team_id=payload.team_id,
        invention_title=payload.invention_title,
        application_status="Draft",
        created_by=user.id,
    )
    db.add(patent)
    await db.commit()
    await db.refresh(patent)
    return patent


@router.get("", response_model=list[PatentOut])
async def list_patents(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    query = await visible_patents_query(db, user=user)
    result = await db.execute(query.order_by(PatentApplication.id.desc()))
    return result.scalars().all()


@router.get("/available-agents", response_model=list[AvailableAgentOut])
async def available_agents(
    _: User = Depends(require_role("INNOVATOR", "ADMIN", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    agents = await list_available_agents(db)
    return [
        AvailableAgentOut(
            id=a.id, full_name=a.full_name, email=a.email, active_assignment_count=c
        )
        for a, c in agents
    ]


@router.get("/{patent_id}", response_model=PatentOut)
async def get_patent(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)
    return patent


async def _require_editable_by(db: AsyncSession, user: User, patent: PatentApplication) -> None:
    """Title edits & (re)assignment: team member (Innovator) or Admin/Super
    Admin — but only a user who can actually see the patent to begin with."""
    await _require_visible(db, user, patent)
    if _is_admin(user):
        return
    if not await is_team_member(db, team_id=patent.team_id, user_id=user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted to edit this application")


@router.patch("/{patent_id}", response_model=PatentOut)
async def update_patent(
    patent_id: int,
    payload: PatentUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_editable_by(db, user, patent)

    if patent.application_status != "Draft":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only Draft applications can be edited"
        )

    patent.invention_title = payload.invention_title
    await db.commit()
    await db.refresh(patent)
    return patent


@router.post("/{patent_id}/submit", response_model=PatentOut)
async def submit_patent(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_editable_by(db, user, patent)

    if patent.application_status != "Draft":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only Draft applications can be submitted")

    # NEW Phase 5 gate: Basic Information (Applicants/Inventors) and the
    # questionnaire must be complete before an application can move out of
    # Draft. Flag if submit should be allowed to proceed without this.
    problems = await basic_info_complete(db, patent=patent)
    if problems:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot submit — {'; '.join(problems)}",
        )

    patent.application_status = "Submitted"
    await log_event(
        db,
        user_id=user.id,
        event_type="PATENT_SUBMITTED",
        entity_type="patent_application",
        entity_id=patent.id,
    )
    await db.commit()
    await db.refresh(patent)
    return patent


# --------------------------------------------------------------------------
# Agent assignment
# --------------------------------------------------------------------------

@router.post("/{patent_id}/assign", response_model=PatentOut)
async def assign_agent(
    patent_id: int,
    payload: AssignAgentRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_editable_by(db, user, patent)

    if patent.application_status not in PRE_ASSIGNMENT_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This application already has an agent who has accepted — it can't be reassigned here",
        )

    agent = await _load_approved_agent_or_400(db, payload.patent_agent_id)

    await perform_assignment(db, patent=patent, agent_id=agent.id, assigned_by_user_id=user.id)
    await db.commit()
    await db.refresh(patent)
    return patent


@router.post("/{patent_id}/reassign", response_model=PatentOut)
async def reassign_agent(
    patent_id: int,
    payload: ReassignAgentRequest,
    user: User = Depends(require_role("ADMIN", "SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Post-acceptance override — Admin/Super Admin only, not available to
    team members (unlike /assign). See module docstring and open item #7."""
    patent = await _get_patent_or_404(db, patent_id)

    if patent.application_status not in POST_ACCEPTANCE_REASSIGNMENT_STATUSES:
        if patent.application_status in PRE_ASSIGNMENT_STATUSES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No agent has accepted this application yet — use /assign or /auto-assign instead",
            )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Applications in '{patent.application_status}' status can't be reassigned",
        )

    if patent.assigned_patent_agent_id == payload.patent_agent_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That agent is already assigned to this application"
        )

    agent = await _load_approved_agent_or_400(db, payload.patent_agent_id)

    await perform_reassignment(
        db,
        patent=patent,
        new_agent_id=agent.id,
        reassigned_by_user_id=user.id,
        reason=payload.reason,
    )
    await db.commit()
    await db.refresh(patent)
    return patent


@router.post("/{patent_id}/auto-assign", response_model=PatentOut)
async def auto_assign_agent(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_editable_by(db, user, patent)

    if patent.application_status not in PRE_ASSIGNMENT_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This application already has an agent who has accepted — it can't be reassigned here",
        )

    candidates = await list_available_agents(db)
    if not candidates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No Patent Agents are available")

    agent, _count = candidates[0]  # lightest workload first
    await perform_assignment(db, patent=patent, agent_id=agent.id, assigned_by_user_id=user.id)
    await db.commit()
    await db.refresh(patent)
    return patent


@router.post("/{patent_id}/assignment/accept", response_model=PatentOut)
async def accept_assignment(
    patent_id: int,
    agent: User = Depends(require_role("PATENT_AGENT")),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    if patent.assigned_patent_agent_id != agent.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent application not found")
    if patent.application_status != "Awaiting Patent Agent Acceptance":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No assignment is awaiting your acceptance")

    assignment = await latest_assignment(db, patent_application_id=patent.id)
    if assignment is None or assignment.patent_agent_id != agent.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No pending assignment found")

    from datetime import datetime, timezone

    assignment.assignment_status = "Accepted"
    assignment.accepted_at = datetime.now(timezone.utc)
    patent.application_status = "Under Review"

    if patent.created_by:
        await notify(
            db,
            user_id=patent.created_by,
            notification_type="Accepted",
            patent_application_id=patent.id,
        )
    await log_event(
        db,
        user_id=agent.id,
        event_type="PATENT_ASSIGNMENT_ACCEPTED",
        entity_type="patent_application",
        entity_id=patent.id,
    )
    await db.commit()
    await db.refresh(patent)
    return patent


@router.post("/{patent_id}/assignment/reject", response_model=PatentOut)
async def reject_assignment(
    patent_id: int,
    payload: RejectAssignmentRequest,
    agent: User = Depends(require_role("PATENT_AGENT")),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    if patent.assigned_patent_agent_id != agent.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent application not found")
    if patent.application_status != "Awaiting Patent Agent Acceptance":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No assignment is awaiting your decision")

    assignment = await latest_assignment(db, patent_application_id=patent.id)
    if assignment is None or assignment.patent_agent_id != agent.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No pending assignment found")

    from datetime import datetime, timezone

    assignment.assignment_status = "Rejected"
    assignment.rejected_at = datetime.now(timezone.utc)
    assignment.rejection_reason = payload.reason

    patent.assigned_patent_agent_id = None
    patent.application_status = "Submitted"  # back in the pool for reassignment

    if patent.created_by:
        await notify(
            db,
            user_id=patent.created_by,
            notification_type="Rejected",
            patent_application_id=patent.id,
        )
    await log_event(
        db,
        user_id=agent.id,
        event_type="PATENT_ASSIGNMENT_REJECTED",
        entity_type="patent_application",
        entity_id=patent.id,
        metadata={"reason": payload.reason} if payload.reason else None,
    )
    await db.commit()
    await db.refresh(patent)
    return patent
