from fastapi import APIRouter, Depends, HTTPException, status
from app.core.security import current_user, active_user, require_roles
from app.core.firebase import db
from app.services.repository import list_docs, patch_doc, now_iso

router = APIRouter()

@router.get('/me')
def me(user: dict = Depends(current_user)):
    return {k: v for k, v in user.items() if not k.startswith('_')}

@router.post('/sync')
def sync_profile(payload: dict | None = None, user: dict = Depends(current_user)):
    """Sync the signed-in Firebase user profile. Firebase client handles sign-in."""
    payload = payload or {}
    allowed = {'full_name', 'phone', 'organization', 'bio'}
    patch = {k: payload[k] for k in allowed if k in payload}
    if patch:
        patch['updated_at'] = now_iso()
        db().collection('users').document(user['uid']).set(patch, merge=True)
    snap = db().collection('users').document(user['uid']).get()
    result = snap.to_dict() or user
    result['uid'] = user['uid']
    return result

@router.post('/logout')
def logout(user: dict = Depends(current_user)):
    # The client should sign out using Firebase Auth; this revokes refresh tokens server-side.
    from firebase_admin import auth
    from app.core.firebase import initialize_firebase
    try:
        auth.revoke_refresh_tokens(user['uid'], app=initialize_firebase())
    except Exception:
        pass
    return {'message': 'Server-side refresh tokens revoked. Sign out on the Firebase client as well.'}

@router.get('/pending-users')
def pending_users(_: dict = Depends(require_roles('ADMIN', 'SUPER_ADMIN'))):
    return [u for u in list_docs('users') if u.get('account_status') == 'pending']

@router.post('/users/{user_id}/approve')
def approve_user(user_id: str, admin: dict = Depends(require_roles('ADMIN', 'SUPER_ADMIN'))):
    ref = db().collection('users').document(user_id)
    snap = ref.get()
    if not snap.exists: raise HTTPException(404, 'User not found.')
    ref.set({'account_status': 'approved', 'approved_by': admin['uid'], 'approved_at': now_iso(), 'updated_at': now_iso()}, merge=True)
    out = ref.get().to_dict() or {}; out['uid'] = user_id; return out

@router.post('/users/{user_id}/reject')
def reject_user(user_id: str, admin: dict = Depends(require_roles('ADMIN', 'SUPER_ADMIN'))):
    ref = db().collection('users').document(user_id)
    if not ref.get().exists: raise HTTPException(404, 'User not found.')
    ref.set({'account_status': 'rejected', 'rejected_by': admin['uid'], 'updated_at': now_iso()}, merge=True)
    out = ref.get().to_dict() or {}; out['uid'] = user_id; return out
