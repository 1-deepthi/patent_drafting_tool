"""Creates rows in `notifications`. Per spec, notifications are strictly
type-driven — never store custom message text here. The frontend renders
copy from a fixed template keyed by notification_type, joined to the
linked patent application for specifics (e.g. invention title) at render
time. Valid types (per the model's own comment): Submitted / Assigned /
Accepted / Rejected / Reassigned / ChangeRequested / DraftGenerated /
FilingRecorded / Granted.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


async def notify(
    db: AsyncSession,
    *,
    user_id: int,
    notification_type: str,
    patent_application_id: int | None = None,
) -> None:
    db.add(
        Notification(
            user_id=user_id,
            patent_application_id=patent_application_id,
            notification_type=notification_type,
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )
    )
