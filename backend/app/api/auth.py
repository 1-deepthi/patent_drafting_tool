"""Authentication & account-approval routes.

Sign-in is Google OAuth 2.0 / OIDC ONLY — no passwords exist anywhere in
this system. Two ways to obtain a session token:

  1. GET /api/auth/google/login -> GET /api/auth/google/callback
     The real flow. Requires GOOGLE_CLIENT_ID/SECRET in .env.

  2. POST /api/auth/dev-login
     A hard-gated bypass for local RBAC testing before Google OAuth
     credentials exist. Returns 404 unless BOTH environment=="development"
     AND DEV_LOGIN_ENABLED=true — so it can never accidentally be reachable
     outside local dev, and doesn't even reveal its existence otherwise.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_user, require_role
from app.core.config import settings
from app.core.database import get_db
from app.core.oauth import oauth
from app.core.security import create_access_token
from app.models import Role, User, UserRole
from app.schemas.auth import (
    ApproveUserRequest,
    DevLoginRequest,
    MeResponse,
    PendingUserOut,
    RejectUserRequest,
    TokenResponse,
    UserOut,
)
from app.services.audit import log_event
from app.services.user_service import (
    get_or_create_dev_user,
    get_or_create_user_from_google,
    permission_codes_for_user,
    serialize_user,
)
from datetime import datetime, timezone

router = APIRouter()


# --------------------------------------------------------------------------
# Real Google OAuth flow
# --------------------------------------------------------------------------

@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:  # noqa: BLE001 — provider/network errors, surfaced generically
        logger.error("Google OAuth callback failed: {}", exc)
        return _redirect_to_frontend(error="oauth_failed")

    userinfo = token.get("userinfo")
    if not userinfo or not userinfo.get("email"):
        return _redirect_to_frontend(error="oauth_no_email")

    try:
        user, is_new = await get_or_create_user_from_google(
            db,
            google_id=userinfo["sub"],
            email=userinfo["email"],
            full_name=userinfo.get("name") or userinfo["email"].split("@")[0],
            profile_picture=userinfo.get("picture"),
        )
    except ValueError as exc:
        await db.rollback()
        logger.warning("Google sign-in conflict: {}", exc)
        return _redirect_to_frontend(error="account_conflict")

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token(user_id=user.id)
    return _redirect_to_frontend(token=access_token, is_new=is_new)


def _redirect_to_frontend(*, token: str | None = None, error: str | None = None, is_new: bool = False):
    from starlette.responses import RedirectResponse

    params: dict[str, str] = {}
    if token:
        params["token"] = token
        if is_new:
            params["new"] = "1"
    if error:
        params["error"] = error
    url = f"{settings.frontend_url}/auth/callback"
    if params:
        url = f"{url}?{urlencode(params)}"
    return RedirectResponse(url)


# --------------------------------------------------------------------------
# Dev-login bypass — see module docstring
# --------------------------------------------------------------------------

@router.post("/dev-login", response_model=TokenResponse)
async def dev_login(payload: DevLoginRequest, db: AsyncSession = Depends(get_db)):
    if not (settings.environment == "development" and settings.dev_login_enabled):
        # 404, not 403 — don't confirm this endpoint exists outside dev.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    try:
        user, _is_new = await get_or_create_dev_user(
            db,
            email=payload.email,
            full_name=payload.full_name,
            default_role_code=payload.role_code,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token(user_id=user.id)
    return TokenResponse(access_token=access_token, user=serialize_user(user))


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------

@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    perms = await permission_codes_for_user(db, user)
    return MeResponse(user=serialize_user(user), permissions=perms)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(user: User = Depends(get_current_active_user)):
    """Sliding-expiry refresh: called by the frontend on activity so the
    30-minute inactivity timeout resets rather than being a hard 30-minute
    session cap. Requires an Approved account (unlike /me)."""
    access_token = create_access_token(user_id=user.id)
    return TokenResponse(access_token=access_token, user=serialize_user(user))


@router.post("/logout")
async def logout(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Stateless JWTs can't be server-side revoked — the frontend discards
    # the token. We only update the state field (never an audit_logs row,
    # per spec: login/logout are explicitly excluded from audit_logs).
    user.last_logout_at = datetime.now(timezone.utc)
    await db.commit()
    return {"detail": "Logged out"}


# --------------------------------------------------------------------------
# Account approval — Super Admin only
# --------------------------------------------------------------------------

@router.get("/pending-users", response_model=list[PendingUserOut])
async def list_pending_users(
    _: User = Depends(require_role("SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.account_status == "Pending", User.is_deleted.is_(False))
    )
    return result.scalars().all()


@router.post("/users/{user_id}/approve", response_model=UserOut)
async def approve_user(
    user_id: int,
    payload: ApproveUserRequest,
    admin: User = Depends(require_role("SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if target is None or target.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    roles_result = await db.execute(select(Role).where(Role.role_code.in_(payload.role_codes)))
    roles = roles_result.scalars().all()
    found_codes = {r.role_code for r in roles}
    missing = set(payload.role_codes) - found_codes
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown role_codes: {sorted(missing)}")

    target.account_status = "Approved"
    target.approved_by = admin.id
    target.approved_at = datetime.now(timezone.utc)

    for role in roles:
        existing = await db.execute(
            select(UserRole).where(UserRole.user_id == target.id, UserRole.role_id == role.id)
        )
        if existing.scalar_one_or_none() is None:
            db.add(UserRole(user_id=target.id, role_id=role.id, assigned_by=admin.id, is_active=True))

    await log_event(
        db,
        user_id=admin.id,
        event_type="USER_APPROVED",
        entity_type="user",
        entity_id=target.id,
        metadata={"role_codes": payload.role_codes},
    )
    await db.commit()
    await db.refresh(target, attribute_names=["user_roles"])
    for ur in target.user_roles:
        await db.refresh(ur, attribute_names=["role"])
    return serialize_user(target)


@router.post("/users/{user_id}/reject", response_model=UserOut)
async def reject_user(
    user_id: int,
    payload: RejectUserRequest,
    admin: User = Depends(require_role("SUPER_ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if target is None or target.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    target.account_status = "Rejected"
    target.approved_by = admin.id
    target.approved_at = datetime.now(timezone.utc)

    await log_event(
        db,
        user_id=admin.id,
        event_type="USER_REJECTED",
        entity_type="user",
        entity_id=target.id,
        metadata={"reason": payload.reason} if payload.reason else None,
    )
    await db.commit()
    await db.refresh(target, attribute_names=["user_roles"])
    return serialize_user(target)
