from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.firebase import verify_id_token, FirebaseNotConfigured, db
from app.core.config import settings

bearer = HTTPBearer(auto_error=False)

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Provide a Firebase ID token as Bearer token.')
    try:
        claims = verify_id_token(credentials.credentials)
        uid = claims.get('uid') or claims.get('sub')
        snap = db().collection('users').document(uid).get()
        profile = snap.to_dict() if snap.exists else None
        if not profile:
            email = (claims.get('email') or '').lower()
            role = 'SUPER_ADMIN' if settings.bootstrap_admin_email and email == settings.bootstrap_admin_email.lower() else 'INNOVATOR'
            profile = {
                'uid': uid, 'email': email, 'full_name': claims.get('name') or '',
                'role_codes': [role], 'account_status': 'approved' if role == 'SUPER_ADMIN' else 'pending',
                'email_verified': bool(claims.get('email_verified')), 'created_at': None,
            }
            db().collection('users').document(uid).set(profile)
        if settings.bootstrap_admin_email and profile.get('email', '').lower() == settings.bootstrap_admin_email.lower():
            profile['role_codes'] = list(set(profile.get('role_codes', []) + ['SUPER_ADMIN']))
            profile['account_status'] = 'approved'
        profile['uid'] = uid
        profile['_token_claims'] = claims
        return profile
    except FirebaseNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Firebase ID token is invalid or expired.') from exc

def active_user(user: dict = Depends(current_user)) -> dict:
    if user.get('account_status') != 'approved':
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Your account is awaiting administrator approval.')
    return user

def require_roles(*roles: str):
    def dependency(user: dict = Depends(active_user)) -> dict:
        if not set(roles).intersection(user.get('role_codes', [])):
            raise HTTPException(status.HTTP_403_FORBIDDEN, 'Insufficient role permissions.')
        return user
    return dependency

def is_admin(user: dict) -> bool:
    return bool({'ADMIN', 'SUPER_ADMIN'} & set(user.get('role_codes', [])))
