"""Report generation + the dashboard summary (Phase 9).

Every report is computed strictly on top of `visible_patents_query` — the
same team/agent/admin scoping Phase 4 already built for the patent list —
so a report never surfaces a row the caller couldn't already see by
listing patents directly. Nothing here is a new authorization boundary,
just aggregation on top of the existing one.

`ReportPermission` (app/models/collaboration.py) existed since Phase 2's
initial migration but was never read or written anywhere until this
session — see Project_Handover_v15.md §17's note about audit_logs being a
similar "built but unused" case. It's role-scoped and download-specific:
every role can *view* a report in the UI (gated by the ordinary
REPORTS_VIEW permission code, seeded in app/seed.py's MODULES list), but
*downloading* (CSV export) additionally requires either an Admin/Super
Admin caller or an explicit ReportPermission(role, report_type,
can_download=True) row, managed via the /permissions/matrix endpoints
below (Super Admin only, mirroring app/api/rbac.py's toggle pattern).
"""

import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    CalendarEvent,
    Notification,
    PatentApplication,
    ReportPermission,
    Role,
    Team,
    User,
    UserRole,
)
from app.services.patent_service import TERMINAL_STATUSES, visible_patents_query
from app.services.team_service import member_team_ids

REPORT_TYPES: dict[str, dict[str, str]] = {
    "STATUS_BREAKDOWN": {
        "label": "Status Breakdown",
        "description": "Count of applications you can see, grouped by lifecycle status.",
    },
    "TEAM_SUMMARY": {
        "label": "Team Summary",
        "description": "Patent counts per team you can see, broken down by status.",
    },
    "AGENT_WORKLOAD": {
        "label": "Agent Workload",
        "description": (
            "Active vs. total assignment counts per Patent Agent, "
            "across applications you can see."
        ),
    },
    "FILING_TIMELINE": {
        "label": "Filing Timeline",
        "description": (
            "Official application number and filing date where recorded, "
            "plus days-in-progress for applications still moving."
        ),
    },
}


def _is_admin(user: User) -> bool:
    codes = {ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role}
    return bool(codes & {"SUPER_ADMIN", "ADMIN"})


def _active_role_codes(user: User) -> set[str]:
    return {ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role}


# ---------------------------------------------------------------------------
# Individual report builders — each returns a list of plain dicts (JSON- and
# CSV-friendly) already ordered for display.
# ---------------------------------------------------------------------------


async def _status_breakdown(db: AsyncSession, *, user: User) -> list[dict]:
    subq = (await visible_patents_query(db, user=user)).subquery()
    result = await db.execute(
        select(subq.c.application_status, func.count())
        .group_by(subq.c.application_status)
        .order_by(func.count().desc())
    )
    return [{"status": status, "count": count} for status, count in result.all()]


async def _team_summary(db: AsyncSession, *, user: User) -> list[dict]:
    subq = (await visible_patents_query(db, user=user)).subquery()
    result = await db.execute(
        select(Team.id, Team.team_name, subq.c.application_status, func.count())
        .select_from(subq)
        .join(Team, Team.id == subq.c.team_id)
        .group_by(Team.id, Team.team_name, subq.c.application_status)
        .order_by(Team.team_name, func.count().desc())
    )
    return [
        {"team_id": tid, "team_name": name, "status": status, "count": count}
        for tid, name, status, count in result.all()
    ]


async def _agent_workload(db: AsyncSession, *, user: User) -> list[dict]:
    subq = (await visible_patents_query(db, user=user)).subquery()
    result = await db.execute(
        select(User.id, User.full_name, User.email, subq.c.application_status, func.count())
        .select_from(subq)
        .join(User, User.id == subq.c.assigned_patent_agent_id)
        .group_by(User.id, User.full_name, User.email, subq.c.application_status)
    )
    by_agent: dict[int, dict] = {}
    for agent_id, name, email, appl_status, count in result.all():
        row = by_agent.setdefault(
            agent_id,
            {
                "agent_id": agent_id,
                "agent_name": name,
                "agent_email": email,
                "active_count": 0,
                "total_count": 0,
            },
        )
        row["total_count"] += count
        if appl_status not in TERMINAL_STATUSES:
            row["active_count"] += count
    return sorted(by_agent.values(), key=lambda r: r["active_count"], reverse=True)


async def _filing_timeline(db: AsyncSession, *, user: User) -> list[dict]:
    query = await visible_patents_query(db, user=user)
    result = await db.execute(
        query.order_by(
            PatentApplication.filing_date.desc().nulls_last(),
            PatentApplication.id.desc(),
        ).limit(500)
    )
    now = datetime.now(timezone.utc)
    rows = []
    for patent in result.scalars().all():
        created = patent.created_at
        days = (now - created).days if created else 0
        rows.append(
            {
                "patent_id": patent.id,
                "invention_title": patent.invention_title,
                "application_status": patent.application_status,
                "official_application_number": patent.official_application_number,
                "filing_date": patent.filing_date,
                "days_since_created": days,
            }
        )
    return rows


_BUILDERS = {
    "STATUS_BREAKDOWN": _status_breakdown,
    "TEAM_SUMMARY": _team_summary,
    "AGENT_WORKLOAD": _agent_workload,
    "FILING_TIMELINE": _filing_timeline,
}


async def build_report(db: AsyncSession, *, user: User, report_type: str) -> list[dict]:
    builder = _BUILDERS.get(report_type)
    if builder is None:
        raise ValueError(f"Unknown report_type: {report_type}")
    return await builder(db, user=user)


def rows_to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


async def can_download(db: AsyncSession, *, user: User, report_type: str) -> bool:
    """The fine-grained, per-report-type gate — separate from the RBAC
    REPORTS_DOWNLOAD permission code checked in app/api/reports.py's
    _require_reports_access(). Admin/Super Admin bypass this one too
    (same "Admin sees/does everything by default" convention as
    visible_patents_query's own admin bypass), but that's the *only*
    gate they bypass automatically — everyone else needs an explicit,
    Super-Admin-granted ReportPermission row for one of their active
    roles, per report type."""
    if _is_admin(user):
        return True
    count = await db.scalar(
        select(func.count(ReportPermission.id))
        .join(Role, Role.id == ReportPermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user.id,
            UserRole.is_active.is_(True),
            ReportPermission.report_type == report_type,
            ReportPermission.can_download.is_(True),
        )
    )
    return bool(count)


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


async def dashboard_summary(db: AsyncSession, *, user: User):
    from app.schemas.reports import DashboardSummary, RecentActivityItem, StatusCount

    visible_subq = (await visible_patents_query(db, user=user)).subquery()

    total = await db.scalar(select(func.count()).select_from(visible_subq))

    status_result = await db.execute(
        select(visible_subq.c.application_status, func.count())
        .group_by(visible_subq.c.application_status)
        .order_by(func.count().desc())
    )
    status_counts = [StatusCount(status=s, count=c) for s, c in status_result.all()]

    role_codes = _active_role_codes(user)

    if role_codes & {"SUPER_ADMIN", "ADMIN"}:
        action_required_count = await db.scalar(
            select(func.count(PatentApplication.id)).where(
                PatentApplication.application_status == "Submitted",
                PatentApplication.assigned_patent_agent_id.is_(None),
            )
        )
        action_required_label = "Submitted applications awaiting agent assignment"
    elif "PATENT_AGENT" in role_codes:
        action_required_count = await db.scalar(
            select(func.count(PatentApplication.id)).where(
                PatentApplication.assigned_patent_agent_id == user.id,
                PatentApplication.application_status == "Awaiting Patent Agent Acceptance",
            )
        )
        action_required_label = "Assignments awaiting your acceptance"
    else:
        team_ids = await member_team_ids(db, user_id=user.id)
        if team_ids:
            action_required_count = await db.scalar(
                select(func.count(PatentApplication.id)).where(
                    PatentApplication.team_id.in_(team_ids),
                    PatentApplication.application_status.in_(["Draft", "Changes Requested"]),
                )
            )
        else:
            action_required_count = 0
        action_required_label = "Applications needing your attention (Draft or Changes Requested)"

    unread_notifications = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    )

    now = datetime.now(timezone.utc)
    upcoming_events_count = await db.scalar(
        select(func.count(CalendarEvent.id))
        .select_from(visible_subq)
        .join(CalendarEvent, CalendarEvent.patent_application_id == visible_subq.c.id)
        .where(CalendarEvent.event_date >= now, CalendarEvent.event_date <= now + timedelta(days=7))
    )

    recent_activity = None
    if role_codes & {"SUPER_ADMIN", "ADMIN"}:
        activity_result = await db.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(10)
        )
        recent_activity = [
            RecentActivityItem.model_validate(row) for row in activity_result.scalars().all()
        ]

    return DashboardSummary(
        total_visible_patents=total or 0,
        status_counts=status_counts,
        action_required_count=action_required_count or 0,
        action_required_label=action_required_label,
        unread_notifications=unread_notifications or 0,
        upcoming_events_count=upcoming_events_count or 0,
        recent_activity=recent_activity,
    )
