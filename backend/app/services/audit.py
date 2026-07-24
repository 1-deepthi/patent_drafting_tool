"""Writes rows to audit_logs.

Per spec: audit_logs covers patent/document/admin activity ONLY.
Login/logout are explicitly excluded — those live solely as
users.last_login_at / last_logout_at state fields (see app/api/auth.py).
Do not call log_event() for login/logout under any circumstances.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def log_event(
    db: AsyncSession,
    *,
    user_id: int | None,
    event_type: str,
    entity_type: str,
    entity_id: int | None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            log_metadata=metadata,
            created_at=datetime.now(timezone.utc),
        )
    )
