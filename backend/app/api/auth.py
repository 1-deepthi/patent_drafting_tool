"""Authentication/profile endpoints.

Sign-in itself happens in the browser with the Firebase JS SDK. The API only
verifies the resulting ID token, syncs the Firestore profile, and serves the
Super Admin approval queue. There is no server-minted JWT and no dev login.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.firebase import db
from app.core.security import (
    active_user,
    current_user,
    is_super_admin,
    permissions_for,
)
from app.services.projections import user_out
from app.services.rbac import ALL_ROLE_CODES
from app.services.repository import get_doc, list_docs, now_iso, sort_docs

router = APIRouter()

PROFILE_FIELDS = (
    "full_name",
    "phone_number",
    "designation",
    "organization",
    "bio",
    "profile_picture",
)


def _touch_last_login(user: dict) -> None:
    """Record sign-in activity at most once every five minutes."""
    last = user.get("last_login_at")
    try:
        parsed = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        parsed = None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed and datetime.now(timezone.utc) - parsed < timedelta(minutes=5):
        return
    db().collection("users").document(user["uid"]).set(
        {"last_login_at": now_iso(), "updated_at": now_iso()}, merge=True
    )
    user["last_login_at"] = now_iso()


@router.get("/me")
def me(user: dict = Depends(current_user)):
    _touch_last_login(user)
    return {"user": user_out(user), "permissions": permissions_for(user)}


@router.post("/sync")
def sync_profile(
    payload: dict | None = None, user: dict = Depends(current_user)
):
    """Upsert the profile fields the client owns and return the full session."""
    payload = payload or {}
    patch = {key: payload[key] for key in PROFILE_FIELDS if key in payload}
    patch["last_login_at"] = now_iso()
    patch["updated_at"] = now_iso()
    db().collection("users").document(user["uid"]).set(patch, merge=True)
    user.update(patch)
    return {"user": user_out(user), "permissions": permissions_for(user)}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: dict = Depends(current_user)):
    """Firebase sessions are revoked client-side; this endpoint is a no-op ACK."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/pending-users")
def pending_users(user: dict = Depends(active_user)):
    if not is_super_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super Admin access required.")
    pending = [
        doc
        for doc in list_docs("users")
        if (doc.get("account_status") or "pending") == "pending"
    ]
    pending = sort_docs(pending, "created_at")
    return [
        {
            "id": doc["id"],
            "email": doc.get("email") or "",
            "full_name": doc.get("full_name") or "",
            "organization": doc.get("organization"),
            "created_at": doc.get("created_at"),
        }
        for doc in pending
    ]


@router.post("/users/{user_id}/approve")
def approve_user(
    user_id: str, payload: dict | None = None, user: dict = Depends(active_user)
):
    if not is_super_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super Admin access required.")
    payload = payload or {}
    role_codes = [str(code).upper() for code in payload.get("role_codes") or []]
    if not role_codes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select at least one role.")
    unknown = sorted(set(role_codes) - set(ALL_ROLE_CODES))
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown role code(s): {', '.join(unknown)}.",
        )
    target = get_doc("users", user_id)
    db().collection("users").document(user_id).set(
        {
            "account_status": "approved",
            "role_codes": sorted(set(role_codes)),
            "is_active": True,
            "approved_by": user["uid"],
            "approved_at": now_iso(),
            "updated_at": now_iso(),
        },
        merge=True,
    )
    target.update(
        {"account_status": "approved", "role_codes": sorted(set(role_codes))}
    )
    return user_out(target)


@router.post("/users/{user_id}/reject")
def reject_user(
    user_id: str, payload: dict | None = None, user: dict = Depends(active_user)
):
    if not is_super_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super Admin access required.")
    target = get_doc("users", user_id)
    db().collection("users").document(user_id).set(
        {
            "account_status": "rejected",
            "rejected_by": user["uid"],
            "rejected_at": now_iso(),
            "updated_at": now_iso(),
        },
        merge=True,
    )
    target.update({"account_status": "rejected"})
    return user_out(target)
