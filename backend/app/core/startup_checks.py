"""Fail-fast production safety checks — Phase 10.

Development and test environments are intentionally permissive (default
secrets, dev-login, wide-open CORS/hosts all need to keep working, and
every earlier phase's live verification depended on that). Production is
not — this module is the one place that draws the line, and it's a pure
function of `Settings` so it's cheap to unit test directly (see
tests/test_hardening.py) without booting a real app or database.

Called once from app/main.py's lifespan, and ONLY when
settings.environment == "production" — see that file. A non-empty
return value means app/main.py raises RuntimeError and refuses to start,
by design: a production deployment with a placeholder JWT secret or
dev-login left on is worse than a deployment that fails loudly at boot.
"""
from app.core.config import Settings

_PLACEHOLDER_JWT_SECRET = "change-this-to-a-long-random-string"
_PLACEHOLDER_SESSION_SECRET = "change-this-to-a-different-long-random-string"
_MIN_SECRET_LENGTH = 32


def find_production_issues(settings: Settings) -> list[str]:
    """Returns human-readable problems with `settings` for a production
    boot. Empty list == safe to start."""
    issues: list[str] = []

    if settings.jwt_secret == _PLACEHOLDER_JWT_SECRET:
        issues.append("JWT_SECRET is still the checked-in placeholder value")
    elif len(settings.jwt_secret) < _MIN_SECRET_LENGTH:
        issues.append(f"JWT_SECRET is shorter than {_MIN_SECRET_LENGTH} characters")

    if settings.session_secret == _PLACEHOLDER_SESSION_SECRET:
        issues.append("SESSION_SECRET is still the checked-in placeholder value")
    elif len(settings.session_secret) < _MIN_SECRET_LENGTH:
        issues.append(f"SESSION_SECRET is shorter than {_MIN_SECRET_LENGTH} characters")

    if settings.jwt_secret and settings.jwt_secret == settings.session_secret:
        issues.append("JWT_SECRET and SESSION_SECRET must not be identical")

    if settings.dev_login_enabled:
        issues.append(
            "DEV_LOGIN_ENABLED is true — this issues real JWTs without Google "
            "sign-in and must never be on in production"
        )

    if not settings.google_client_id or not settings.google_client_secret:
        issues.append(
            "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not set — no one could sign in"
        )

    cors = settings.cors_origins.strip()
    if cors == "*":
        issues.append(
            "CORS_ORIGINS is wildcarded — combined with allow_credentials=True "
            "browsers reject this anyway, and it's a needless CSRF-adjacent "
            "opening even where they don't"
        )
    if "localhost" in cors or "127.0.0.1" in cors:
        issues.append("CORS_ORIGINS still includes a localhost origin")

    if settings.allowed_hosts.strip() == "*":
        issues.append("ALLOWED_HOSTS is wildcarded — set it to your real domain(s)")

    if not settings.google_redirect_uri.startswith("https://"):
        issues.append("GOOGLE_REDIRECT_URI is not HTTPS")
    if not settings.frontend_url.startswith("https://"):
        issues.append("FRONTEND_URL is not HTTPS")

    if settings.storage_provider == "local":
        issues.append(
            "STORAGE_PROVIDER is 'local' — generated documents and uploads "
            "won't survive a redeploy or be shared across instances; set 'r2' "
            "(see app/services/storage/factory.py)"
        )

    return issues
