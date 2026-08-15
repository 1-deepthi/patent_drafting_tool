"""Reports & Dashboards (Phase 9).

Two routers:
  - `router`             -> mounted at /api/reports. Dashboard is available
    to any approved active user (personal, already-visible-scoped data,
    same posture as the calendar's "my events" endpoint).

    Report listing/viewing/export is gated by `_require_reports_access`
    below, which is deliberately NOT plain `require_permission()`: every
    other cross-cutting admin feature in this app (templates.py, the RBAC
    dashboard itself, pending-user approval in auth.py) is gated by
    `require_role("ADMIN", "SUPER_ADMIN")` — Admin is treated as trusted
    for cross-patent tooling by default, no explicit grant required.
    Nothing in the app actually calls `require_permission()` before this
    session; the role_permissions matrix (app/api/rbac.py) exists but
    gated nothing. Wiring Reports up to it verbatim would make Reports
    the one feature where even an Admin is locked out until a Super Admin
    manually flips a switch — inconsistent with how Admin works
    everywhere else. So `_require_reports_access` bypasses the
    permission-code check for Admin/Super Admin (matching the rest of
    the app's Admin-is-trusted convention) and only falls through to the
    real, data-driven REPORTS_VIEW/REPORTS_DOWNLOAD permission-code check
    for other roles (Innovator, Patent Agent) — exactly where a
    data-driven, per-role toggle earns its keep, since those roles have
    no other standing access to cross-patent reporting.
  - `permissions_router`  -> mounted at /api/reports/permissions,
    Super-Admin-only management of the report_permissions matrix —
    mirrors app/api/rbac.py's /matrix + /toggle pattern exactly. This
    one, finer-grained per-report-type download gate applies to every
    role — Admin/Super Admin included — see
    reports_service.can_download()'s docstring for why that layer keeps
    its own, separate Admin bypass instead.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_role, user_has_permission
from app.core.database import get_db
from app.models import ReportPermission, Role, User
from app.schemas.auth import RoleOut
from app.schemas.reports import (
    DashboardSummary,
    ReportOut,
    ReportPermissionGrant,
    ReportPermissionMatrixResponse,
    ReportTypeCatalogOut,
    ReportTypeOut,
)
from app.services.audit import log_event
from app.services.reports_service import (
    REPORT_TYPES,
    _is_admin,
    build_report,
    can_download,
    dashboard_summary,
    rows_to_csv,
)

router = APIRouter()
permissions_router = APIRouter(dependencies=[Depends(require_role("SUPER_ADMIN"))])


def _require_reports_access(permission_code: str):
    """Admin/Super Admin always pass; every other role needs the ordinary
    REPORTS_VIEW/REPORTS_DOWNLOAD permission code granted via
    /api/rbac/toggle. See this module's docstring for why."""

    async def _dependency(
        user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if _is_admin(user) or await user_has_permission(db, user, permission_code):
            return user
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Missing required permission: {permission_code}",
        )

    return _dependency


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await dashboard_summary(db, user=user)


@router.get("", response_model=list[ReportTypeOut])
async def list_report_types(
    user: User = Depends(_require_reports_access("REPORTS_VIEW")),
    db: AsyncSession = Depends(get_db),
):
    out = []
    for report_type, meta in REPORT_TYPES.items():
        out.append(
            ReportTypeOut(
                report_type=report_type,
                label=meta["label"],
                description=meta["description"],
                can_download=await can_download(db, user=user, report_type=report_type),
            )
        )
    return out


@router.get("/{report_type}", response_model=ReportOut)
async def get_report(
    report_type: str,
    user: User = Depends(_require_reports_access("REPORTS_VIEW")),
    db: AsyncSession = Depends(get_db),
):
    if report_type not in REPORT_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report type")

    rows = await build_report(db, user=user, report_type=report_type)
    return ReportOut(
        report_type=report_type,
        label=REPORT_TYPES[report_type]["label"],
        generated_at=datetime.now(timezone.utc),
        row_count=len(rows),
        rows=rows,
    )


@router.get("/{report_type}/export")
async def export_report(
    report_type: str,
    user: User = Depends(_require_reports_access("REPORTS_DOWNLOAD")),
    db: AsyncSession = Depends(get_db),
):
    if report_type not in REPORT_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report type")

    if not await can_download(db, user=user, report_type=report_type):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your role isn't permitted to download this report — ask a Super Admin to grant it",
        )

    rows = await build_report(db, user=user, report_type=report_type)
    csv_text = rows_to_csv(rows)

    await log_event(
        db,
        user_id=user.id,
        event_type="REPORT_DOWNLOADED",
        entity_type="report",
        entity_id=None,
        metadata={"report_type": report_type, "row_count": len(rows)},
    )
    await db.commit()

    filename = f"{report_type.lower()}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Super-Admin-only: which report types each role may download
# ---------------------------------------------------------------------------


async def _matrix(db: AsyncSession) -> ReportPermissionMatrixResponse:
    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    grants = (
        (await db.execute(select(ReportPermission).where(ReportPermission.can_download.is_(True))))
        .scalars()
        .all()
    )
    return ReportPermissionMatrixResponse(
        roles=[RoleOut.model_validate(r) for r in roles],
        report_types=[
            ReportTypeCatalogOut(report_type=rt, label=meta["label"], description=meta["description"])
            for rt, meta in REPORT_TYPES.items()
        ],
        grants=[
            ReportPermissionGrant(role_id=g.role_id, report_type=g.report_type) for g in grants
        ],
    )


@permissions_router.get("/matrix", response_model=ReportPermissionMatrixResponse)
async def get_report_permission_matrix(db: AsyncSession = Depends(get_db)):
    return await _matrix(db)


@permissions_router.post("/toggle", response_model=ReportPermissionMatrixResponse)
async def toggle_report_permission(
    payload: ReportPermissionGrant,
    grant: bool,
    admin: User = Depends(require_role("SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    if payload.report_type not in REPORT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown report type")

    role = await db.get(Role, payload.role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")

    existing = await db.execute(
        select(ReportPermission).where(
            ReportPermission.role_id == payload.role_id,
            ReportPermission.report_type == payload.report_type,
        )
    )
    row = existing.scalar_one_or_none()

    if grant:
        if row is None:
            db.add(
                ReportPermission(
                    role_id=payload.role_id,
                    report_type=payload.report_type,
                    can_download=True,
                    granted_by=admin.id,
                )
            )
        else:
            row.can_download = True
            row.granted_by = admin.id
    else:
        if row is not None:
            row.can_download = False

    await log_event(
        db,
        user_id=admin.id,
        event_type="REPORT_PERMISSION_GRANTED" if grant else "REPORT_PERMISSION_REVOKED",
        entity_type="role",
        entity_id=payload.role_id,
        metadata={"report_type": payload.report_type},
    )
    await db.commit()
    return await _matrix(db)
