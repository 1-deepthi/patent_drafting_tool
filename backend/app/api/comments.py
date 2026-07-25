"""Comments (Phase 8): a permanent discussion thread per patent
application, visible to anyone who can view the application. Per
app/models/collaboration.py::Comment, this is deliberately append-only —
no update or delete endpoint exists here, and none should be added.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.api.patents import _get_patent_or_404, _require_visible
from app.core.database import get_db
from app.models import Comment, User
from app.schemas.collaboration import CommentCreate, CommentOut
from app.services.notification import notify

router = APIRouter()

# Comment/file activity notifications (NEW — see open item #28 in the
# handover). Not part of the original fixed notification_type set
# (Submitted/Assigned/Accepted/Rejected/ChangeRequested/DraftGenerated/
# FilingRecorded/Granted) — invented for this pass, flag if the real spec
# wants a different value or no notification at all here.
NOTIFICATION_TYPE_COMMENT_ADDED = "CommentAdded"


async def _notify_other_participants(
    db: AsyncSession, *, patent, actor_id: int, notification_type: str
) -> None:
    """Notifies the patent's innovator (created_by) and assigned agent,
    excluding whoever just performed the action, so people don't get
    notified about their own comment/upload."""
    recipient_ids = {
        uid for uid in (patent.created_by, patent.assigned_patent_agent_id)
        if uid is not None and uid != actor_id
    }
    for uid in recipient_ids:
        await notify(
            db, user_id=uid, notification_type=notification_type,
            patent_application_id=patent.id,
        )


@router.get("/{patent_id}/comments", response_model=list[CommentOut])
async def list_comments(
    patent_id: int,
    response: Response,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    total = await db.scalar(
        select(func.count()).select_from(Comment)
        .where(Comment.patent_application_id == patent_id)
    )
    response.headers["X-Total-Count"] = str(total or 0)

    # Comment has no ORM relationship to User (see models/collaboration.py),
    # so join explicitly rather than selectinload.
    result = await db.execute(
        select(Comment, User.full_name)
        .join(User, User.id == Comment.user_id)
        .where(Comment.patent_application_id == patent_id)
        .order_by(Comment.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    return [
        CommentOut(
            id=c.id,
            patent_application_id=c.patent_application_id,
            user_id=c.user_id,
            user_full_name=full_name,
            comment_text=c.comment_text,
            created_at=c.created_at,
        )
        for c, full_name in result.all()
    ]


@router.post("/{patent_id}/comments", response_model=CommentOut, status_code=201)
async def create_comment(
    patent_id: int,
    payload: CommentCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    patent = await _get_patent_or_404(db, patent_id)
    await _require_visible(db, user, patent)

    comment = Comment(
        patent_application_id=patent_id,
        user_id=user.id,
        comment_text=payload.comment_text,
        created_at=datetime.now(timezone.utc),
    )
    db.add(comment)
    await _notify_other_participants(
        db, patent=patent, actor_id=user.id,
        notification_type=NOTIFICATION_TYPE_COMMENT_ADDED,
    )
    await db.commit()
    await db.refresh(comment)

    return CommentOut(
        id=comment.id,
        patent_application_id=comment.patent_application_id,
        user_id=comment.user_id,
        user_full_name=user.full_name,
        comment_text=comment.comment_text,
        created_at=comment.created_at,
    )
