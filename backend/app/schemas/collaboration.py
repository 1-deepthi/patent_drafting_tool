from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Comments — permanent discussion thread, never edited/deleted (see
# app/models/collaboration.py::Comment). No CommentUpdate/delete schema
# exists on purpose.
# ---------------------------------------------------------------------------


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    user_id: int
    user_full_name: str | None = None
    comment_text: str
    created_at: datetime


class CommentCreate(BaseModel):
    comment_text: str = Field(min_length=1, max_length=5000)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    uploaded_by: int | None
    uploaded_by_name: str | None = None
    original_file_name: str | None
    mime_type: str | None
    file_size_bytes: int | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Notifications — type-driven, no stored text (see
# app/models/collaboration.py::Notification). invention_title is joined in
# at read time so the frontend can render its fixed per-type template.
# ---------------------------------------------------------------------------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int | None
    invention_title: str | None = None
    notification_type: str | None
    is_read: bool
    created_at: datetime


class UnreadCountOut(BaseModel):
    unread_count: int


# ---------------------------------------------------------------------------
# Calendar events
# ---------------------------------------------------------------------------

CALENDAR_EVENT_TYPES = ("Filing Deadline", "Examination", "Hearing", "Reminder")


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patent_application_id: int
    invention_title: str | None = None
    event_type: str | None
    event_date: datetime | None
    created_by: int | None


class CalendarEventCreate(BaseModel):
    event_type: str
    event_date: datetime


# ---------------------------------------------------------------------------
# Templates (NEW — closes open item #24, the Phase 7 gap: no Templates UI
# or real merging existed yet). One shared, versioned template row per
# document_type, per app/models/template.py's own docstring. Editable only
# by Admin/Super Admin — enforced in app/api/templates.py via require_role.
# ---------------------------------------------------------------------------


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_type: str
    version_number: int
    file_path: str | None = None
    original_file_name: str | None = None
    is_active: bool
    edited_by: int | None = None
    edited_by_name: str | None = None

    # Placeholder-validation info (open item #31) — only ever populated on
    # the upload response itself, never persisted or backfilled when
    # listing existing templates, so these are None on every other read.
    unknown_placeholders: list[str] | None = None
    unused_known_placeholders: list[str] | None = None
    template_parse_error: str | None = None
