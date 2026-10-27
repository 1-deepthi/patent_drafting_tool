"""Firebase Authentication guards and user-profile bootstrap.

Firebase verifies the ID token; Firestore stores the authorization profile
(`role_codes` array, `account_status`). Roles are never trusted from the
client (ADR-002). Legacy SQL users/JWT helpers are gone — see ADR-005.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.firebase import FirebaseNotConfigured, db, verify_id_token
from app.services.repository import get_doc_or_none, now_iso

bearer = HTTPBearer(auto_error=False)

APPROVED = "approved"


def _bootstrap_email(email: str) -> bool:
    return bool(
        settings.bootstrap_admin_email
        and email
        and email.lower() == settings.bootstrap_admin_email.lower()
    )


def _new_profile(uid: str, claims: dict) -> dict:
    email = (claims.get("email") or "").lower()
    bootstrap = _bootstrap_email(email)
    stamp = now_iso()
    return {
        "email": email,
        "full_name": claims.get("name") or "",
        "profile_picture": claims.get("picture") or None,
        "phone_number": None,
        "designation": None,
        "organization": None,
        "bio": None,
        "role_codes": ["SUPER_ADMIN"] if bootstrap else ["INNOVATOR"],
        "account_status": "approved" if bootstrap else "pending",
        "is_active": True,
        "email_verified": bool(claims.get("email_verified")),
        "last_login_at": stamp,
        "created_at": stamp,
        "updated_at": stamp,
    }


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    """Verify the Firebase ID token and return the caller's profile."""
    if not credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Provide a Firebase ID token as a Bearer token.",
        )

    try:
        claims = verify_id_token(credentials.credentials)
    except FirebaseNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - firebase raises several token errors
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Firebase ID token is invalid or expired.",
        ) from exc

    uid = claims.get("uid") or claims.get("sub")
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token is missing a user ID.")

    profile = get_doc_or_none("users", uid)
    if profile is None:
        profile = _new_profile(uid, claims)
        db().collection("users").document(uid).set(profile)
        profile["id"] = uid

    # The bootstrap account is always an approved Super Admin, even if an
    # older profile predates that setting. Write only when something changed.
    if _bootstrap_email(profile.get("email", "")):
        roles = set(profile.get("role_codes") or [])
        if "SUPER_ADMIN" not in roles or profile.get("account_status") != APPROVED:
            roles.add("SUPER_ADMIN")
            patch = {
                "role_codes": sorted(roles),
                "account_status": APPROVED,
                "is_active": True,
                "updated_at": now_iso(),
            }
            db().collection("users").document(uid).set(patch, merge=True)
            profile.update(patch)

    profile["uid"] = uid
    profile["_claims"] = claims
    return profile


def active_user(user: dict = Depends(current_user)) -> dict:
    if user.get("account_status") != APPROVED:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your account is awaiting administrator approval.",
        )
    if user.get("is_active") is False:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled.")
    return user


def require_roles(*roles: str):
    def dependency(user: dict = Depends(active_user)) -> dict:
        if not set(roles).intersection(user.get("role_codes") or []):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Insufficient role permissions."
            )
        return user

    return dependency


def is_admin(user: dict) -> bool:
    return bool({"ADMIN", "SUPER_ADMIN"} & set(user.get("role_codes") or []))


def is_super_admin(user: dict) -> bool:
    return "SUPER_ADMIN" in set(user.get("role_codes") or [])


def permissions_for(user: dict) -> list[str]:
    """Effective permission codes, cached on the per-request profile."""
    cached = user.get("_permissions")
    if cached is not None:
        return cached
    from app.services.rbac import permission_codes

    codes = permission_codes(user)
    user["_permissions"] = codes
    return codes


def has_permission(user: dict, code: str) -> bool:
    if is_super_admin(user):
        return True
    return code in permissions_for(user)


def ensure_permission(user: dict, code: str) -> None:
    if not has_permission(user, code):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Your role does not include the {code} permission.",
        )
