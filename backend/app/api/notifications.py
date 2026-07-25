"""Notifications (Phase 8): user-scoped, never patent-scoped in the URL —
a user only ever sees their own rows. Per app/services/notification.py,
rows are strictly type-driven; invention_title is joined in here purely
for the frontend's fixed per-type template, never stored on the row
itself.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.models import Notification, PatentApplication, User
from app.schemas.collaboration import NotificationOut, UnreadCountOut

router = APIRouter()


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    total = await db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
    )
    response.headers["X-Total-Count"] = str(total or 0)

    result = await db.execute(
        select(Notification, PatentApplication.invention_title)
        .outerjoin(
            PatentApplication,
            PatentApplication.id == Notification.patent_application_id,
        )
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        NotificationOut(
            id=n.id,
            patent_application_id=n.patent_application_id,
            invention_title=title,
            notification_type=n.notification_type,
            is_read=n.is_read,
            created_at=n.created_at,
        )
        for n, title in result.all()
    ]


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    )
    return UnreadCountOut(unread_count=result.scalar_one())


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")

    notification.is_read = True
    await db.commit()
    await db.refresh(notification)

    title = None
    if notification.patent_application_id:
        patent = await db.get(PatentApplication, notification.patent_application_id)
        title = patent.invention_title if patent else None

    return NotificationOut(
        id=notification.id,
        patent_application_id=notification.patent_application_id,
        invention_title=title,
        notification_type=notification.notification_type,
        is_read=notification.is_read,
        created_at=notification.created_at,
    )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
