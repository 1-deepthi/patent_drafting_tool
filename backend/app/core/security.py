"""Stateless JWT session tokens.

Per product decision: no sessions table, no server-side revocation list.
A token is valid until its `exp` claim passes. The 30-minute inactivity
timeout is implemented as a sliding expiry: every authenticated request
that succeeds causes the frontend to silently refresh the token (see
POST /api/auth/refresh), so `exp` always reflects "30 minutes from the
last request" rather than "30 minutes from login". If the token's `exp`
has passed, the request is rejected and the user must sign in again —
there is nothing in the DB to revoke.
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

ALGORITHM = settings.jwt_algorithm


class TokenError(Exception):
    """Raised for any invalid/expired/malformed token."""


def create_access_token(*, user_id: int, expires_minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int:
    """Returns the user_id encoded in the token, or raises TokenError."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expired — please sign in again") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid session token") from exc

    sub = payload.get("sub")
    if sub is None:
        raise TokenError("Malformed session token")
    try:
        return int(sub)
    except ValueError as exc:
        raise TokenError("Malformed session token") from exc
