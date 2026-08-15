"""Auth & RBAC dependencies used throughout the API.

Layering (each wraps the previous):
  get_current_user        -> valid JWT, user exists, not deleted/inactive.
                              Used by /api/auth/me so a Pending user can
                              still check their own status.
  get_current_active_user -> above + account_status == "Approved".
                              Use this for every real business endpoint.
  require_permission(...)  -> above + the user's active roles grant the
                              given permission_code via role_permissions.
  require_role(...)        -> above + the user holds one of the given
                              role_codes. Use sparingly — prefer
                              require_permission so access stays
                              data-driven instead of hardcoded by role.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import TokenError, decode_access_token
from app.models import Permission, Role, RolePermission, User, UserRole

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        user_id = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
    )
    user = result.scalar_one_or_none()

    if user is None or user.is_deleted:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account has been suspended")

    return user


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if user.account_status != "Approved":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Account is {user.account_status.lower()} — awaiting Super Admin approval",
        )
    return user


def _active_role_codes(user: User) -> set[str]:
    return {
        ur.role.role_code
        for ur in user.user_roles
        if ur.is_active and ur.role is not None
    }


async def _permission_codes_for_roles(db: AsyncSession, role_codes: set[str]) -> set[str]:
    if not role_codes:
        return set()
    result = await db.execute(
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.role_code.in_(role_codes), RolePermission.is_active.is_(True))
    )
    return {row[0] for row in result.all()}


async def user_has_permission(db: AsyncSession, user: User, permission_code: str) -> bool:
    """Reusable check behind require_permission() — pulled out so other
    dependencies (e.g. app/api/reports.py's Admin/Super Admin bypass) can
    reuse the same role_permissions lookup without duplicating the query."""
    granted = await _permission_codes_for_roles(db, _active_role_codes(user))
    return permission_code in granted


def require_permission(permission_code: str):
    async def _dependency(
        user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not await user_has_permission(db, user, permission_code):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Missing required permission: {permission_code}",
            )
        return user

    return _dependency


def require_role(*role_codes: str):
    allowed = set(role_codes)

    async def _dependency(user: User = Depends(get_current_active_user)) -> User:
        if not _active_role_codes(user) & allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires one of these roles: {', '.join(sorted(allowed))}",
            )
        return user

    return _dependency
