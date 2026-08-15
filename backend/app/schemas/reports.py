from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.auth import RoleOut

# ---------------------------------------------------------------------------
# Dashboard — a personal, role-tailored summary. No permission gate beyond
# being an approved active user, same posture as GET /api/calendar/events:
# it only ever shows data the caller could already see via
# visible_patents_query.
# ---------------------------------------------------------------------------


class StatusCount(BaseModel):
    status: str
    count: int


class RecentActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    event_type: str | None
    entity_type: str | None
    entity_id: int | None
    created_at: datetime


class DashboardSummary(BaseModel):
    total_visible_patents: int
    status_counts: list[StatusCount]
    action_required_count: int
    action_required_label: str
    unread_notifications: int
    upcoming_events_count: int
    # Admin/Super Admin only — the last 10 audit_logs rows. None for every
    # other role, since audit_logs is otherwise a write-only table (see
    # Project_Handover_v15.md §17) and isn't meant to be a general activity
    # feed for Innovators/Agents.
    recent_activity: list[RecentActivityItem] | None = None


# ---------------------------------------------------------------------------
# Report type catalog + fine-grained download permissions
# (app/models/collaboration.py::ReportPermission)
# ---------------------------------------------------------------------------


class ReportTypeCatalogOut(BaseModel):
    report_type: str
    label: str
    description: str


class ReportTypeOut(ReportTypeCatalogOut):
    can_download: bool


class StatusBreakdownRow(BaseModel):
    status: str
    count: int


class TeamSummaryRow(BaseModel):
    team_id: int
    team_name: str
    status: str
    count: int


class AgentWorkloadRow(BaseModel):
    agent_id: int
    agent_name: str
    agent_email: str
    active_count: int
    total_count: int


class FilingTimelineRow(BaseModel):
    patent_id: int
    invention_title: str
    application_status: str
    official_application_number: str | None
    filing_date: datetime | None
    days_since_created: int


class ReportOut(BaseModel):
    report_type: str
    label: str
    generated_at: datetime
    row_count: int
    rows: list[dict]


# ---------------------------------------------------------------------------
# Super-Admin-only management of the report_permissions matrix — mirrors
# app/schemas/rbac.py::RolePermissionGrant / RbacMatrixResponse.
# ---------------------------------------------------------------------------


class ReportPermissionGrant(BaseModel):
    role_id: int
    report_type: str


class ReportPermissionMatrixResponse(BaseModel):
    roles: list[RoleOut]
    report_types: list[ReportTypeCatalogOut]
    grants: list[ReportPermissionGrant]
