"""Questionnaire step (workflow item 5): the guided invention questionnaire,
branching by invention_type. Basic Information (applicants/inventors) lives
in basic_info.py, not here — see app/models/questionnaire.py docstring.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.patents import _get_patent_or_404, _require_editable_by, _require_visible
from app.core.database import get_db
from app.models import User
from app.schemas.questionnaire import QuestionnaireOut, QuestionnaireUpdate, QuestionnaireVersionOut
from app.services.audit import log_event
from app.services.patent_service import PRE_ASSIGNMENT_STATUSES
from app.services.questionnaire_service import (
    apply_update,
    get_or_create_questionnaire,
    list_versions,
    missing_required_fields,
    snapshot_version,
)

# Editing/submitting the questionnaire is allowed through any
# PRE_ASSIGNMENT_STATUSES status, not just "Draft". assign/auto-assign can
# move a patent straight from "Draft" to "Awaiting Patent Agent Acceptance"
# (a tested, intentional design — see
# test_can_assign_agent_even_before_submission_but_not_after_acceptance in
# tests/test_assignment_workflow.py). If this gate stayed Draft-only, an
# application assigned before submission would have its questionnaire
# locked forever, since nothing ever moves it back to Draft. See
# Project_Handover_v14.md §12.3 for the original finding.
_QUESTIONNAIRE_EDITABLE_ERROR = (
    "The questionnaire can only be edited before a Patent Agent has "
    "accepted the assignment"
)
_QUESTIONNAIRE_SUBMITTABLE_ERROR = (
    "The questionnaire can only be submitted before a Patent Agent has "
    "accepted the assignment"
)

router = APIRouter()


@router.get("/{patent_id}/questionnaire", response_model=QuestionnaireOut)
async def get_questionnaire(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)
    q = await get_or_create_questionnaire(db, patent=patent)
    await db.commit()
    await db.refresh(q)
    return q


@router.patch("/{patent_id}/questionnaire", response_model=QuestionnaireOut)
async def update_questionnaire(
    patent_id: int,
    payload: QuestionnaireUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_editable_by(db, user, patent)
    if patent.application_status not in PRE_ASSIGNMENT_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _QUESTIONNAIRE_EDITABLE_ERROR)

    q = await get_or_create_questionnaire(db, patent=patent)
    apply_update(q, payload.model_dump(exclude_unset=True))
    patent.questionnaire_status = q.questionnaire_status  # keep summary column in sync

    await db.commit()
    await db.refresh(q)
    return q


@router.post("/{patent_id}/questionnaire/submit", response_model=QuestionnaireOut)
async def submit_questionnaire(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_editable_by(db, user, patent)
    if patent.application_status not in PRE_ASSIGNMENT_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _QUESTIONNAIRE_SUBMITTABLE_ERROR)

    q = await get_or_create_questionnaire(db, patent=patent)
    missing = missing_required_fields(q)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Questionnaire is incomplete — missing: {', '.join(missing)}",
        )

    q.questionnaire_status = "Completed"
    patent.questionnaire_status = "Completed"
    await snapshot_version(db, q=q, created_by=user.id)
    await log_event(
        db,
        user_id=user.id,
        event_type="QUESTIONNAIRE_SUBMITTED",
        entity_type="patent_application",
        entity_id=patent.id,
    )
    await db.commit()
    await db.refresh(q)
    return q


@router.get("/{patent_id}/questionnaire/versions", response_model=list[QuestionnaireVersionOut])
async def get_questionnaire_versions(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)
    q = await get_or_create_questionnaire(db, patent=patent)
    await db.commit()
    return await list_versions(db, questionnaire_id=q.id)
