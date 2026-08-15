"""Phase 10 (hardening/deployment) tests.

Covers app/core/startup_checks.py (pure function, no app/DB needed),
app/core/middleware.py (via the real client fixture — headers should be
on every response), and app/core/rate_limit.py (via the real dev-login
endpoint, since that's the one it's actually wired onto).

Rate limiting is OFF by default for the whole suite (see conftest.py) so
the many dev-login calls other test files make don't trip it. The two
tests here that need it ON flip `limiter.enabled` directly and restore it
in a finally — same toggle-and-revert convention test_admin_rbac.py uses
for role_permissions grants.
"""
from app.core.config import Settings
from app.core.rate_limit import limiter
from app.core.startup_checks import find_production_issues

# --------------------------------------------------------------------------
# find_production_issues — pure, no app/DB needed
# --------------------------------------------------------------------------

def _prod_ready_settings(**overrides) -> Settings:
    """A Settings instance that passes every production check, so each
    test below can override exactly the one field it's checking."""
    defaults = dict(
        environment="production",
        jwt_secret="a" * 40,
        session_secret="b" * 40,
        dev_login_enabled=False,
        google_client_id="real-client-id",
        google_client_secret="real-client-secret",
        google_redirect_uri="https://api.example.com/api/auth/google/callback",
        frontend_url="https://app.example.com",
        cors_origins="https://app.example.com",
        allowed_hosts="api.example.com",
        storage_provider="r2",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_fully_configured_production_settings_pass():
    assert find_production_issues(_prod_ready_settings()) == []


def test_placeholder_jwt_secret_flagged():
    settings = _prod_ready_settings(jwt_secret="change-this-to-a-long-random-string")
    issues = find_production_issues(settings)
    assert any("JWT_SECRET" in issue for issue in issues)


def test_short_session_secret_flagged():
    settings = _prod_ready_settings(session_secret="too-short")
    issues = find_production_issues(settings)
    assert any("SESSION_SECRET" in issue for issue in issues)


def test_identical_secrets_flagged():
    same = "c" * 40
    settings = _prod_ready_settings(jwt_secret=same, session_secret=same)
    issues = find_production_issues(settings)
    assert any("must not be identical" in issue for issue in issues)


def test_dev_login_enabled_flagged():
    settings = _prod_ready_settings(dev_login_enabled=True)
    issues = find_production_issues(settings)
    assert any("DEV_LOGIN_ENABLED" in issue for issue in issues)


def test_missing_google_credentials_flagged():
    settings = _prod_ready_settings(google_client_id="", google_client_secret="")
    issues = find_production_issues(settings)
    assert any("GOOGLE_CLIENT_ID" in issue for issue in issues)


def test_wildcard_cors_flagged():
    settings = _prod_ready_settings(cors_origins="*")
    issues = find_production_issues(settings)
    assert any("CORS_ORIGINS is wildcarded" in issue for issue in issues)


def test_localhost_cors_flagged():
    settings = _prod_ready_settings(cors_origins="http://localhost:5173")
    issues = find_production_issues(settings)
    assert any("localhost" in issue for issue in issues)


def test_wildcard_allowed_hosts_flagged():
    settings = _prod_ready_settings(allowed_hosts="*")
    issues = find_production_issues(settings)
    assert any("ALLOWED_HOSTS" in issue for issue in issues)


def test_non_https_redirect_uri_flagged():
    settings = _prod_ready_settings(
        google_redirect_uri="http://api.example.com/api/auth/google/callback"
    )
    issues = find_production_issues(settings)
    assert any("GOOGLE_REDIRECT_URI" in issue for issue in issues)


def test_non_https_frontend_url_flagged():
    settings = _prod_ready_settings(frontend_url="http://app.example.com")
    issues = find_production_issues(settings)
    assert any("FRONTEND_URL" in issue for issue in issues)


def test_local_storage_provider_flagged():
    settings = _prod_ready_settings(storage_provider="local")
    issues = find_production_issues(settings)
    assert any("STORAGE_PROVIDER" in issue for issue in issues)


def test_development_settings_are_never_checked_by_this_function_directly():
    """find_production_issues() itself doesn't gate on environment — that
    decision lives in app/main.py's lifespan (only ever calls this when
    environment == "production"). Confirms the function still reports
    accurately even if called against a dev-shaped Settings, so a caller
    can't get a false "all clear" just because environment says dev."""
    dev_shaped = Settings(environment="production")  # everything else default
    issues = find_production_issues(dev_shaped)
    assert issues  # the checked-in defaults are exactly the placeholders


# --------------------------------------------------------------------------
# Security headers + request-ID middleware — via the real client
# --------------------------------------------------------------------------

async def test_security_headers_present_on_success_response(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in resp.headers["permissions-policy"]
    # HSTS is dev/test-off, only added when settings.environment == "production"
    assert "strict-transport-security" not in resp.headers


async def test_security_headers_present_on_error_response(client):
    """Headers must survive an error response too — 404s, 401s, etc. are
    exactly where a browser most benefits from clickjacking/MIME-sniffing
    protection, and it's easy to accidentally scope a middleware to only
    the happy path."""
    resp = await client.get("/api/definitely-not-a-real-route")
    assert resp.status_code == 404
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"


async def test_request_id_present_and_echoed_back(client):
    resp = await client.get("/health", headers={"X-Request-ID": "test-fixed-id-123"})
    assert resp.headers["x-request-id"] == "test-fixed-id-123"


async def test_request_id_generated_when_not_supplied(client):
    resp = await client.get("/health")
    assert resp.headers["x-request-id"]  # non-empty, some UUID was generated


# --------------------------------------------------------------------------
# Rate limiting — deliberately flips the module-level limiter on, since the
# whole suite runs with RATE_LIMIT_ENABLED=false (see conftest.py)
# --------------------------------------------------------------------------

async def test_dev_login_rate_limited_past_configured_threshold(client):
    from app.core.config import settings as live_settings

    limiter.enabled = True
    try:
        limit = int(live_settings.rate_limit_auth.split("/")[0])
        last_status = None
        for i in range(limit + 2):
            resp = await client.post(
                "/api/auth/dev-login",
                json={
                    "role_code": "INNOVATOR",
                    "email": f"rate-limit-{i}@fixture-test.dev",
                    "full_name": "Rate Limit Test",
                },
            )
            last_status = resp.status_code
        assert last_status == 429
    finally:
        limiter.enabled = False


async def test_rate_limiting_disabled_by_default_for_the_suite(client):
    """Sanity check on the test setup itself: with the limiter off (the
    suite's default), calling dev-login well past the configured
    threshold never 429s. If this ever fails, every other test file's
    dev-login-heavy fixtures (make_user, create_submitted_patent, etc.)
    would start flaking."""
    assert limiter.enabled is False
    for i in range(15):
        resp = await client.post(
            "/api/auth/dev-login",
            json={
                "role_code": "INNOVATOR",
                "email": f"no-limit-{i}@fixture-test.dev",
                "full_name": "No Limit Test",
            },
        )
        assert resp.status_code == 200
