from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Permission, Role, RolePermission, User, UserRole
from app.schemas.auth import UserOut


def active_role_codes(user: User) -> list[str]:
    return sorted(
        {ur.role.role_code for ur in user.user_roles if ur.is_active and ur.role is not None}
    )


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone_number=user.phone_number,
        profile_picture=user.profile_picture,
        designation=user.designation,
        organization=user.organization,
        account_status=user.account_status,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        roles=active_role_codes(user),
    )


async def permission_codes_for_user(db: AsyncSession, user: User) -> list[str]:
    role_codes = active_role_codes(user)
    if not role_codes:
        return []
    result = await db.execute(
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.role_code.in_(role_codes), RolePermission.is_active.is_(True))
        .distinct()
    )
    return sorted(row[0] for row in result.all())


async def _load_with_roles(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
    )
    return result.scalar_one()


async def get_or_create_user_from_google(
    db: AsyncSession,
    *,
    google_id: str,
    email: str,
    full_name: str,
    profile_picture: str | None,
) -> tuple[User, bool]:
    """Matches an incoming Google sign-in to a User row.

    Match order:
      1. By google_id (returning user).
      2. By email, where the existing row's google_id is still the
         Phase-2 bootstrap placeholder ("pending-first-login:<email>") —
         this claims the seeded bootstrap Super Admin (or any admin-
         precreated account) on its first real Google sign-in, per the
         Phase 2 handover note.
      3. Otherwise: brand-new account, created as account_status="Pending".

    Returns (user, is_new_account).
    """
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return await _load_with_roles(db, user.id), False

    result = await db.execute(select(User).where(User.email == email))
    existing_by_email = result.scalar_one_or_none()
    if existing_by_email is not None:
        if existing_by_email.google_id.startswith("pending-first-login:"):
            existing_by_email.google_id = google_id
            if profile_picture:
                existing_by_email.profile_picture = profile_picture
            await db.flush()
            return await _load_with_roles(db, existing_by_email.id), False
        # Email collision with a different, already-claimed google_id.
        # Do NOT silently merge accounts — surface this as a conflict.
        raise ValueError(
            f"An account already exists for {email} under a different Google identity"
        )

    new_user = User(
        google_id=google_id,
        email=email,
        full_name=full_name,
        profile_picture=profile_picture,
        account_status="Pending",
        is_active=True,
        is_deleted=False,
    )
    db.add(new_user)
    await db.flush()
    return await _load_with_roles(db, new_user.id), True


async def get_or_create_dev_user(
    db: AsyncSession,
    *,
    email: str,
    full_name: str | None,
    default_role_code: str,
) -> tuple[User, bool]:
    """Dev-login-only helper — see app/api/auth.py for the hard environment
    gate. Auto-approves new users for local testing convenience only."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return await _load_with_roles(db, user.id), False

    role_result = await db.execute(select(Role).where(Role.role_code == default_role_code))
    role = role_result.scalar_one_or_none()
    if role is None:
        raise ValueError(f"Unknown role_code: {default_role_code}")

    new_user = User(
        google_id=f"dev-login:{email}",
        email=email,
        full_name=full_name or email.split("@")[0],
        account_status="Approved",
        is_active=True,
        is_deleted=False,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(new_user)
    await db.flush()
    db.add(UserRole(user_id=new_user.id, role_id=role.id, is_active=True))
    await db.flush()
    return await _load_with_roles(db, new_user.id), True
