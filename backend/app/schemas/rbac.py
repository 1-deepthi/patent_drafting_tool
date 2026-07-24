from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.auth import PermissionOut, RoleOut


class RolePermissionGrant(BaseModel):
    role_id: int
    permission_id: int


class RbacMatrixResponse(BaseModel):
    """Roles, permissions, and which (role_id, permission_id) pairs are
    currently granted — the frontend renders this as a checkbox grid."""

    roles: list[RoleOut]
    permissions: list[PermissionOut]
    grants: list[RolePermissionGrant]


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    account_status: str
    is_active: bool
    roles: list[str]
    created_at: datetime
