"""Calendar events (Phase 8): deadlines, examinations, hearings, and
reminders. Per app/models/collaboration.py::CalendarEvent, every row
belongs to exactly one patent application (patent_application_id is
non-nullable) — there's no such thing as a calendar event unattached to
an application. Creating/deleting an event is restricted the same way
document generation is (see app/api/documents.py): the assigned Patent
Agent or an Admin/Super Admin. Anyone who can view the application may
list its events.

Two routers are exposed:
  - `router`        -> mounted under /api/patents, nested per-patent CRUD.
  - `calendar_router` -> mounted at /api/calendar, a cross-patent "my
    upcoming events" view for the Calendar page.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.patents import _get_patent_or_404, _is_admin, _require_visible
from app.core.database import get_db
from app.models import CalendarEvent, PatentApplication, User
from app.schemas.collaboration import CALENDAR_EVENT_TYPES, CalendarEventCreate, CalendarEventOut
from app.services.patent_service import visible_patents_query

router = APIRouter()
calendar_router = APIRouter()


async def _require_agent_or_admin(db: AsyncSession, user: User, patent: PatentApplication) -> None:
    await _require_visible(db, user, patent)
    if _is_admin(user):
        return
    if patent.assigned_patent_agent_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned Patent Agent or an Admin may manage calendar events for this application",
        )


@router.get("/{patent_id}/calendar-events", response_model=list[CalendarEventOut])
async def list_calendar_events(
    patent_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    result = await db.execute(
        select(CalendarEvent)
        .where(CalendarEvent.patent_application_id == patent_id)
        .order_by(CalendarEvent.event_date.asc())
    )
    return [
        CalendarEventOut(
            id=e.id,
            patent_application_id=e.patent_application_id,
            invention_title=patent.invention_title,
            event_type=e.event_type,
            event_date=e.event_date,
            created_by=e.created_by,
        )
        for e in result.scalars().all()
    ]


@router.post(
    "/{patent_id}/calendar-events",
    response_model=CalendarEventOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_calendar_event(
    patent_id: int,
    payload: CalendarEventCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_agent_or_admin(db, user, patent)

    if payload.event_type not in CALENDAR_EVENT_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"event_type must be one of: {', '.join(CALENDAR_EVENT_TYPES)}",
        )

    event = CalendarEvent(
        patent_application_id=patent_id,
        event_type=payload.event_type,
        event_date=payload.event_date,
        created_by=user.id,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    return CalendarEventOut(
        id=event.id,
        patent_application_id=event.patent_application_id,
        invention_title=patent.invention_title,
        event_type=event.event_type,
        event_date=event.event_date,
        created_by=event.created_by,
    )


@router.delete("/{patent_id}/calendar-events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar_event(
    patent_id: int,
    event_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_agent_or_admin(db, user, patent)

    event = await db.get(CalendarEvent, event_id)
    if event is None or event.patent_application_id != patent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Calendar event not found")

    await db.delete(event)
    await db.commit()


@calendar_router.get("/events", response_model=list[CalendarEventOut])
async def list_my_events(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Every calendar event across every patent application this user can
    see — powers the standalone Calendar page rather than a per-patent tab."""
    visible = (await visible_patents_query(db, user=user)).subquery()

    result = await db.execute(
        select(CalendarEvent, visible.c.invention_title)
        .join(visible, visible.c.id == CalendarEvent.patent_application_id)
        .order_by(CalendarEvent.event_date.asc())
    )
    return [
        CalendarEventOut(
            id=e.id,
            patent_application_id=e.patent_application_id,
            invention_title=title,
            event_type=e.event_type,
            event_date=e.event_date,
            created_by=e.created_by,
        )
        for e, title in result.all()
    ]
