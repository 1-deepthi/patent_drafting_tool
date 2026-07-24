"""Basic Information step (workflow item 4): Applicants and Inventors as
structured records under a Patent Application — NOT free text, NOT Teams.
Same visibility rules as the parent patent (via _require_visible); editing
is restricted to Draft applications, same as title edits in patents.py.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.patents import _get_patent_or_404, _require_editable_by, _require_visible
from app.core.database import get_db
from app.models import Applicant, Inventor, User
from app.schemas.legal_party import (
    ApplicantCreate,
    ApplicantOut,
    ApplicantUpdate,
    InventorCreate,
    InventorOut,
    InventorUpdate,
    ReorderRequest,
)
from app.services.legal_party_service import (
    clear_other_primary_applicants,
    list_applicants,
    list_inventors,
    next_applicant_order,
    next_inventor_order,
    reorder_applicants,
    reorder_inventors,
)

router = APIRouter()


async def _require_draft_editable(db: AsyncSession, user: User, patent_id: int):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_editable_by(db, user, patent)
    if patent.application_status != "Draft":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Basic Information can only be edited while the application is in Draft",
        )
    return patent


# --------------------------------------------------------------------------
# Applicants
# --------------------------------------------------------------------------

@router.get("/{patent_id}/applicants", response_model=list[ApplicantOut])
async def list_applicants_endpoint(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)
    return await list_applicants(db, patent_application_id=patent_id)


@router.post(
    "/{patent_id}/applicants", response_model=ApplicantOut, status_code=status.HTTP_201_CREATED
)
async def create_applicant(
    patent_id: int,
    payload: ApplicantCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)

    order = await next_applicant_order(db, patent_application_id=patent_id)
    if payload.is_primary:
        await clear_other_primary_applicants(db, patent_application_id=patent_id, keep_id=None)

    applicant = Applicant(
        patent_application_id=patent_id,
        display_order=order,
        **payload.model_dump(),
    )
    db.add(applicant)
    await db.commit()
    await db.refresh(applicant)
    return applicant


@router.patch("/{patent_id}/applicants/{applicant_id}", response_model=ApplicantOut)
async def update_applicant(
    patent_id: int,
    applicant_id: int,
    payload: ApplicantUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)

    applicant = await db.get(Applicant, applicant_id)
    if applicant is None or applicant.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Applicant not found")

    if payload.is_primary:
        await clear_other_primary_applicants(
            db, patent_application_id=patent_id, keep_id=applicant_id
        )
    for field, value in payload.model_dump().items():
        setattr(applicant, field, value)

    await db.commit()
    await db.refresh(applicant)
    return applicant


@router.delete("/{patent_id}/applicants/{applicant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_applicant(
    patent_id: int,
    applicant_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)

    applicant = await db.get(Applicant, applicant_id)
    if applicant is None or applicant.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Applicant not found")

    await db.delete(applicant)
    await db.commit()


@router.post("/{patent_id}/applicants/reorder", response_model=list[ApplicantOut])
async def reorder_applicants_endpoint(
    patent_id: int,
    payload: ReorderRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)
    try:
        result = await reorder_applicants(
            db, patent_application_id=patent_id, ordered_ids=payload.ordered_ids
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return result


# --------------------------------------------------------------------------
# Inventors
# --------------------------------------------------------------------------

@router.get("/{patent_id}/inventors", response_model=list[InventorOut])
async def list_inventors_endpoint(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)
    return await list_inventors(db, patent_application_id=patent_id)


@router.post(
    "/{patent_id}/inventors", response_model=InventorOut, status_code=status.HTTP_201_CREATED
)
async def create_inventor(
    patent_id: int,
    payload: InventorCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)

    order = await next_inventor_order(db, patent_application_id=patent_id)
    inventor = Inventor(
        patent_application_id=patent_id,
        inventor_order=order,
        **payload.model_dump(),
    )
    db.add(inventor)
    await db.commit()
    await db.refresh(inventor)
    return inventor


@router.patch("/{patent_id}/inventors/{inventor_id}", response_model=InventorOut)
async def update_inventor(
    patent_id: int,
    inventor_id: int,
    payload: InventorUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)

    inventor = await db.get(Inventor, inventor_id)
    if inventor is None or inventor.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventor not found")

    for field, value in payload.model_dump().items():
        setattr(inventor, field, value)

    await db.commit()
    await db.refresh(inventor)
    return inventor


@router.delete("/{patent_id}/inventors/{inventor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inventor(
    patent_id: int,
    inventor_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)

    inventor = await db.get(Inventor, inventor_id)
    if inventor is None or inventor.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventor not found")

    await db.delete(inventor)
    await db.commit()


@router.post("/{patent_id}/inventors/reorder", response_model=list[InventorOut])
async def reorder_inventors_endpoint(
    patent_id: int,
    payload: ReorderRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_draft_editable(db, user, patent_id)
    try:
        result = await reorder_inventors(
            db, patent_application_id=patent_id, ordered_ids=payload.ordered_ids
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return result
