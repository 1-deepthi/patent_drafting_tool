"""Seeds the four roles, a starter permission set, and one bootstrap
Super Admin account. Run once against a fresh database, after migrations:

    python -m app.seed

The bootstrap Super Admin has no google_id yet — it's a placeholder row
matched by email on first real Google sign-in (wire this matching logic
into the OAuth callback in Phase 3). Set SEED_SUPER_ADMIN_EMAIL before
running, or edit the constant below.
"""

import asyncio
import os

from loguru import logger
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Permission, Role, RolePermission, User

SEED_SUPER_ADMIN_EMAIL = os.getenv("SEED_SUPER_ADMIN_EMAIL", "superadmin@example.com")

ROLES = [
    ("Super Admin", "SUPER_ADMIN", True),
    ("Admin", "ADMIN", True),
    ("Patent Agent", "PATENT_AGENT", True),
    ("Innovator", "INNOVATOR", True),
]

# Module-level actions per the Role & Permission Management dashboard (D3).
# Expand this list as each phase adds new modules/actions.
MODULES = ["Patent", "User", "Reports", "Templates", "Settings"]
ACTIONS = ["View", "Create", "Edit", "Delete", "Generate", "Download"]

# Super Admin gets every permission; other roles start with none assigned —
# assign the rest through the Role & Permission dashboard built in Phase 3.
FULL_ACCESS_ROLE_CODE = "SUPER_ADMIN"


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        # --- Roles ---
        role_by_code: dict[str, Role] = {}
        for name, code, is_system in ROLES:
            existing = await session.scalar(select(Role).where(Role.role_code == code))
            if existing:
                role_by_code[code] = existing
                continue
            role = Role(role_name=name, role_code=code, is_system_role=is_system)
            session.add(role)
            await session.flush()
            role_by_code[code] = role
            logger.info("Created role: {}", code)

        # --- Permissions ---
        permissions: list[Permission] = []
        for module in MODULES:
            for action in ACTIONS:
                code = f"{module.upper()}_{action.upper()}"
                existing = await session.scalar(
                    select(Permission).where(Permission.permission_code == code)
                )
                if existing:
                    permissions.append(existing)
                    continue
                perm = Permission(
                    permission_name=f"{action} {module}",
                    permission_code=code,
                    module_name=module,
                    action=action,
                )
                session.add(perm)
                await session.flush()
                permissions.append(perm)
        logger.info("Seeded {} permissions across {} modules", len(permissions), len(MODULES))

        # --- Grant Super Admin every permission ---
        super_admin = role_by_code[FULL_ACCESS_ROLE_CODE]
        for perm in permissions:
            existing = await session.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == super_admin.id,
                    RolePermission.permission_id == perm.id,
                )
            )
            if not existing:
                session.add(
                    RolePermission(role_id=super_admin.id, permission_id=perm.id, is_active=True)
                )
        logger.info("Granted Super Admin all {} permissions", len(permissions))

        # --- Bootstrap Super Admin user ---
        existing_user = await session.scalar(
            select(User).where(User.email == SEED_SUPER_ADMIN_EMAIL)
        )
        if not existing_user:
            bootstrap_user = User(
                google_id=f"pending-first-login:{SEED_SUPER_ADMIN_EMAIL}",
                email=SEED_SUPER_ADMIN_EMAIL,
                full_name="Super Admin",
                account_status="Approved",
                is_active=True,
                is_deleted=False,
            )
            session.add(bootstrap_user)
            await session.flush()

            from app.models import UserRole  # local import to avoid unused import above

            session.add(UserRole(user_id=bootstrap_user.id, role_id=super_admin.id, is_active=True))
            logger.info(
                "Created bootstrap Super Admin for {} — google_id will be matched/updated "
                "on first real Google sign-in (wire this into the Phase 3 OAuth callback).",
                SEED_SUPER_ADMIN_EMAIL,
            )
        else:
            logger.info("Bootstrap Super Admin already exists for {}", SEED_SUPER_ADMIN_EMAIL)

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
