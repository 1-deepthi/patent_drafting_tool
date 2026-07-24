from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_name: str
    role_code: str
    is_system_role: bool


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    permission_name: str
    permission_code: str
    module_name: str | None
    action: str | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    phone_number: str | None
    profile_picture: str | None
    designation: str | None
    organization: str | None
    account_status: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[str] = Field(default_factory=list)


class MeResponse(BaseModel):
    user: UserOut
    permissions: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class DevLoginRequest(BaseModel):
    """Dev-only bypass. See app/api/auth.py — hard-gated to development."""

    email: EmailStr
    full_name: str | None = None
    # Role to assign ONLY if this creates a brand-new user. Ignored for an
    # existing user (their existing roles are used as-is).
    role_code: str = "INNOVATOR"


class ApproveUserRequest(BaseModel):
    # Roles to grant on approval. Required — an approved user with zero
    # roles can't do anything meaningful on the platform.
    role_codes: list[str] = Field(min_length=1)


class RejectUserRequest(BaseModel):
    reason: str | None = None


class PendingUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    organization: str | None
    created_at: datetime


class AssignRoleRequest(BaseModel):
    role_code: str


class RolePermissionToggleRequest(BaseModel):
    role_id: int
    permission_id: int
    grant: bool
