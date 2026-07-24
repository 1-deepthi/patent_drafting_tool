"""Role & Permission management dashboard — full V1 feature per spec item 18.

Restricted to Super Admin only. This dashboard can grant/revoke ANY
permission to ANY role, including Admin — letting Admin manage its own
permission grants here would be a privilege-escalation path, so this is
deliberately Super-Admin-only rather than shared with Admin. (Flagged as
an assumption in the handover — revisit if that's not the intent.)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_role
from app.core.database import get_db
from app.models import Permission, Role, RolePermission, User, UserRole
from app.schemas.auth import AssignRoleRequest
from app.schemas.rbac import RbacMatrixResponse, RolePermissionGrant, UserAdminOut
from app.services.audit import log_event
from app.services.user_service import active_role_codes
from datetime import datetime, timezone

router = APIRouter(dependencies=[Depends(require_role("SUPER_ADMIN"))])


@router.get("/matrix", response_model=RbacMatrixResponse)
async def get_matrix(db: AsyncSession = Depends(get_db)):
    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    permissions = (await db.execute(select(Permission).order_by(Permission.id))).scalars().all()
    grants = (
        (await db.execute(select(RolePermission).where(RolePermission.is_active.is_(True))))
        .scalars()
        .all()
    )
    return RbacMatrixResponse(
        roles=roles,
        permissions=permissions,
        grants=[
            RolePermissionGrant(role_id=g.role_id, permission_id=g.permission_id) for g in grants
        ],
    )


@router.post("/toggle", response_model=RbacMatrixResponse)
async def toggle_permission(
    payload: RolePermissionGrant,
    grant: bool,
    admin: User = Depends(require_role("SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(Role, payload.role_id)
    permission = await db.get(Permission, payload.permission_id)
    if role is None or permission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role or permission not found")

    existing = await db.execute(
        select(RolePermission).where(
            RolePermission.role_id == payload.role_id,
            RolePermission.permission_id == payload.permission_id,
        )
    )
    row = existing.scalar_one_or_none()

    if grant:
        if row is None:
            db.add(
                RolePermission(
                    role_id=payload.role_id,
                    permission_id=payload.permission_id,
                    assigned_by=admin.id,
                    is_active=True,
                )
            )
        else:
            row.is_active = True
    else:
        if row is not None:
            row.is_active = False

    await log_event(
        db,
        user_id=admin.id,
        event_type="ROLE_PERMISSION_GRANTED" if grant else "ROLE_PERMISSION_REVOKED",
        entity_type="role",
        entity_id=payload.role_id,
        metadata={"permission_code": permission.permission_code},
    )
    await db.commit()
    return await get_matrix(db)


@router.get("/users", response_model=list[UserAdminOut])
async def list_all_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User)
        .where(User.is_deleted.is_(False))
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
        .order_by(User.id)
    )
    users = result.scalars().all()
    return [
        UserAdminOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            account_status=u.account_status,
            is_active=u.is_active,
            roles=active_role_codes(u),
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/users/{user_id}/roles")
async def assign_role(
    user_id: int,
    payload: AssignRoleRequest,
    admin: User = Depends(require_role("SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if target is None or target.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    role = (
        await db.execute(select(Role).where(Role.role_code == payload.role_code))
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown role_code: {payload.role_code}")

    existing = await db.execute(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
    )
    row = existing.scalar_one_or_none()
    if row is not None and row.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User already holds this role")

    if row is not None:
        row.is_active = True
        row.revoked_at = None
        row.revoked_by = None
        row.assigned_by = admin.id
    else:
        db.add(UserRole(user_id=user_id, role_id=role.id, assigned_by=admin.id, is_active=True))

    await log_event(
        db,
        user_id=admin.id,
        event_type="USER_ROLE_ASSIGNED",
        entity_type="user",
        entity_id=user_id,
        metadata={"role_code": payload.role_code},
    )
    await db.commit()
    return {"detail": f"Role {payload.role_code} assigned"}


@router.delete("/users/{user_id}/roles/{role_code}")
async def revoke_role(
    user_id: int,
    role_code: str,
    admin: User = Depends(require_role("SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id and role_code == "SUPER_ADMIN":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Cannot revoke your own Super Admin role"
        )

    role = (
        await db.execute(select(Role).where(Role.role_code == role_code))
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")

    row = (
        await db.execute(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
        )
    ).scalar_one_or_none()
    if row is None or not row.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User does not hold this active role")

    row.is_active = False
    row.revoked_by = admin.id
    row.revoked_at = datetime.now(timezone.utc)

    await log_event(
        db,
        user_id=admin.id,
        event_type="USER_ROLE_REVOKED",
        entity_type="user",
        entity_id=user_id,
        metadata={"role_code": role_code},
    )
    await db.commit()
    return {"detail": f"Role {role_code} revoked"}
