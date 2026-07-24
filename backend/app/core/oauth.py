"""Google OAuth 2.0 / OIDC client, registered via Authlib.

This is the ONLY supported sign-in mechanism for the platform — there are
no passwords anywhere. Requires GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET to
be set in .env (see GETTING_STARTED.md for how to create them in Google
Cloud Console). Until those are set, real Google sign-in will fail at the
provider redirect — use the dev-login bypass (app/api/auth.py) instead.
"""

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings

oauth = OAuth()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
