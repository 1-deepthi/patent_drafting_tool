from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Applicant, Inventor


async def next_applicant_order(db: AsyncSession, *, patent_application_id: int) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Applicant.display_order), 0)).where(
            Applicant.patent_application_id == patent_application_id
        )
    )
    return result.scalar_one() + 1


async def next_inventor_order(db: AsyncSession, *, patent_application_id: int) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Inventor.inventor_order), 0)).where(
            Inventor.patent_application_id == patent_application_id
        )
    )
    return result.scalar_one() + 1


async def list_applicants(db: AsyncSession, *, patent_application_id: int) -> list[Applicant]:
    result = await db.execute(
        select(Applicant)
        .where(Applicant.patent_application_id == patent_application_id)
        .order_by(Applicant.display_order)
    )
    return list(result.scalars().all())


async def list_inventors(db: AsyncSession, *, patent_application_id: int) -> list[Inventor]:
    result = await db.execute(
        select(Inventor)
        .where(Inventor.patent_application_id == patent_application_id)
        .order_by(Inventor.inventor_order)
    )
    return list(result.scalars().all())


async def clear_other_primary_applicants(
    db: AsyncSession, *, patent_application_id: int, keep_id: int | None
) -> None:
    """Enforces 'at most one primary applicant' at the service layer with a
    clean error-free UX (unset the others) rather than relying solely on
    the DB's partial unique index to reject the request."""
    applicants = await list_applicants(db, patent_application_id=patent_application_id)
    for a in applicants:
        if a.id != keep_id and a.is_primary:
            a.is_primary = False


async def reorder_applicants(
    db: AsyncSession, *, patent_application_id: int, ordered_ids: list[int]
) -> list[Applicant]:
    applicants = await list_applicants(db, patent_application_id=patent_application_id)
    by_id = {a.id: a for a in applicants}
    if set(ordered_ids) != set(by_id.keys()):
        raise ValueError("ordered_ids must be exactly the set of this application's applicant IDs")

    # Two-phase write avoids transiently colliding with the unique
    # (patent_application_id, display_order) constraint mid-update.
    for a in applicants:
        a.display_order += 100_000
    await db.flush()
    for position, applicant_id in enumerate(ordered_ids, start=1):
        by_id[applicant_id].display_order = position
    await db.flush()
    return await list_applicants(db, patent_application_id=patent_application_id)


async def reorder_inventors(
    db: AsyncSession, *, patent_application_id: int, ordered_ids: list[int]
) -> list[Inventor]:
    inventors = await list_inventors(db, patent_application_id=patent_application_id)
    by_id = {i.id: i for i in inventors}
    if set(ordered_ids) != set(by_id.keys()):
        raise ValueError("ordered_ids must be exactly the set of this application's inventor IDs")

    for i in inventors:
        i.inventor_order += 100_000
    await db.flush()
    for position, inventor_id in enumerate(ordered_ids, start=1):
        by_id[inventor_id].inventor_order = position
    await db.flush()
    return await list_inventors(db, patent_application_id=patent_application_id)
