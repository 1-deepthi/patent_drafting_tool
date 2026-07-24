"""AI drafting (workflow item 8): Gemini (or the stub provider — see
app/services/ai/) generates patent document content SECTION BY SECTION from
the latest submitted QuestionnaireVersion. Only the assigned Patent Agent or
an Admin/Super Admin may trigger generation, and only once the agent has
accepted the assignment (application_status == "Under Review") — the same
visibility rules as the parent patent apply for read access.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.patents import _get_patent_or_404, _is_admin, _require_visible
from app.core.database import get_db
from app.models import AIOutput, User
from app.schemas.draft import (
    AIOutputOut,
    DraftSectionSlot,
    GenerateDraftRequest,
    GenerateDraftResponse,
)
from app.services.ai import get_ai_provider
from app.services.draft_service import (
    SECTION_TYPES,
    DraftGenerationNotAllowed,
    can_generate,
    generate_sections,
    latest_completed_questionnaire_version,
    latest_outputs_by_section,
)

router = APIRouter()


async def _require_agent_or_admin(db: AsyncSession, user: User, patent) -> None:
    await _require_visible(db, user, patent)
    if _is_admin(user):
        return
    if patent.assigned_patent_agent_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin may manage AI drafting for this application",
        )


@router.get("/{patent_id}/draft", response_model=list[DraftSectionSlot])
async def list_draft_sections(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    qv = await latest_completed_questionnaire_version(db, patent_application_id=patent_id)
    latest_by_section = (
        await latest_outputs_by_section(db, questionnaire_version_id=qv.id) if qv else {}
    )
    return [
        DraftSectionSlot(section_type=st, latest=latest_by_section.get(st))
        for st in SECTION_TYPES
    ]


@router.get("/{patent_id}/draft/{section_type}/versions", response_model=list[AIOutputOut])
async def list_section_versions(
    patent_id: int,
    section_type: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    if section_type not in SECTION_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown section type")

    qv = await latest_completed_questionnaire_version(db, patent_application_id=patent_id)
    if qv is None:
        return []

    result = await db.execute(
        select(AIOutput)
        .where(
            AIOutput.questionnaire_version_id == qv.id,
            AIOutput.section_type == section_type,
        )
        .order_by(AIOutput.version_number.desc())
    )
    return result.scalars().all()


@router.post("/{patent_id}/draft/generate", response_model=GenerateDraftResponse)
async def generate_draft(
    patent_id: int,
    payload: GenerateDraftRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_agent_or_admin(db, user, patent)

    try:
        qv = await can_generate(db, patent=patent)
    except DraftGenerationNotAllowed as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from exc

    section_types = payload.section_types or list(SECTION_TYPES)
    unknown = [s for s in section_types if s not in SECTION_TYPES]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown section_types: {unknown}"
        )

    provider = get_ai_provider()
    outputs = await generate_sections(
        db, patent=patent, qv=qv, section_types=section_types, provider=provider
    )
    return GenerateDraftResponse(
        questionnaire_version_id=qv.id,
        questionnaire_version_number=qv.version_number,
        outputs=outputs,
    )
