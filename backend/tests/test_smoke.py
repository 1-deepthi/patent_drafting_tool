"""Offline smoke tests: the app boots, the contract is mounted, and the
pure-Python services behave. No Firebase credentials are required.
"""
import asyncio
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.core.config import (
    DEFAULT_SELF_HOSTED_UPLOAD_BYTES,
    DEFAULT_VERCEL_UPLOAD_BYTES,
    MIB,
    MULTIPART_OVERHEAD_BYTES,
    VERCEL_BODY_LIMIT_BYTES,
    Settings,
)
from app.services import documents, drafting
from app.services.rbac import (
    ALL_PERMISSION_IDS,
    ALL_ROLE_CODES,
    DEFAULT_GRANTS,
    REPORT_TYPE_NAMES,
    matrix,
)

# Paths the React client calls. Kept as a literal list on purpose: if one of
# them silently disappears from the API the frontend breaks at runtime, which
# no type-checker would catch.
CONTRACT_PATHS = {
    ("get", "/api/config/capabilities"),
    ("get", "/api/auth/me"),
    ("post", "/api/auth/logout"),
    ("post", "/api/auth/sync"),
    ("get", "/api/auth/pending-users"),
    ("post", "/api/auth/users/{user_id}/approve"),
    ("post", "/api/auth/users/{user_id}/reject"),
    ("get", "/api/teams"),
    ("post", "/api/teams"),
    ("get", "/api/teams/{team_id}"),
    ("post", "/api/teams/{team_id}/members"),
    ("delete", "/api/teams/{team_id}/members/{member_id}"),
    ("get", "/api/patents"),
    ("post", "/api/patents"),
    ("get", "/api/patents/available-agents"),
    ("get", "/api/patents/{patent_id}"),
    ("post", "/api/patents/{patent_id}/submit"),
    ("post", "/api/patents/{patent_id}/assign"),
    ("post", "/api/patents/{patent_id}/auto-assign"),
    ("post", "/api/patents/{patent_id}/reassign"),
    ("post", "/api/patents/{patent_id}/assignment/accept"),
    ("post", "/api/patents/{patent_id}/assignment/reject"),
    ("get", "/api/patents/{patent_id}/applicants"),
    ("post", "/api/patents/{patent_id}/applicants"),
    ("patch", "/api/patents/{patent_id}/applicants/{applicant_id}"),
    ("delete", "/api/patents/{patent_id}/applicants/{applicant_id}"),
    ("post", "/api/patents/{patent_id}/applicants/reorder"),
    ("get", "/api/patents/{patent_id}/inventors"),
    ("post", "/api/patents/{patent_id}/inventors"),
    ("patch", "/api/patents/{patent_id}/inventors/{inventor_id}"),
    ("delete", "/api/patents/{patent_id}/inventors/{inventor_id}"),
    ("post", "/api/patents/{patent_id}/inventors/reorder"),
    ("get", "/api/patents/{patent_id}/questionnaire"),
    ("patch", "/api/patents/{patent_id}/questionnaire"),
    ("post", "/api/patents/{patent_id}/questionnaire/submit"),
    ("get", "/api/patents/{patent_id}/questionnaire/versions"),
    ("get", "/api/patents/{patent_id}/draft"),
    ("post", "/api/patents/{patent_id}/draft/generate"),
    ("get", "/api/patents/{patent_id}/draft/{section_type}/versions"),
    ("get", "/api/patents/{patent_id}/comments"),
    ("post", "/api/patents/{patent_id}/comments"),
    ("get", "/api/patents/{patent_id}/files"),
    ("post", "/api/patents/{patent_id}/files"),
    ("get", "/api/patents/{patent_id}/files/{file_id}/download"),
    ("delete", "/api/patents/{patent_id}/files/{file_id}"),
    ("get", "/api/patents/{patent_id}/calendar-events"),
    ("post", "/api/patents/{patent_id}/calendar-events"),
    ("delete", "/api/patents/{patent_id}/calendar-events/{event_id}"),
    ("get", "/api/calendar/events"),
    ("get", "/api/patents/{patent_id}/documents"),
    ("post", "/api/patents/{patent_id}/documents/generate"),
    ("get", "/api/patents/{patent_id}/documents/jobs"),
    ("post", "/api/patents/{patent_id}/documents/jobs/{job_id}/retry"),
    ("get", "/api/patents/{patent_id}/documents/{document_id}/versions"),
    ("get", "/api/patents/{patent_id}/documents/{document_id}/download"),
    ("get", "/api/patents/{patent_id}/documents/versions/{version_id}/download"),
    ("get", "/api/templates/document-types"),
    ("get", "/api/templates"),
    ("post", "/api/templates"),
    ("post", "/api/templates/{template_id}/activate"),
    ("delete", "/api/templates/{template_id}"),
    ("get", "/api/notifications"),
    ("get", "/api/notifications/unread-count"),
    ("patch", "/api/notifications/{notification_id}/read"),
    ("post", "/api/notifications/read-all"),
    ("get", "/api/reports/dashboard"),
    ("get", "/api/reports"),
    ("get", "/api/reports/{report_type}"),
    ("get", "/api/reports/{report_type}/export"),
    ("get", "/api/reports/permissions/matrix"),
    ("post", "/api/reports/permissions/toggle"),
    ("get", "/api/rbac/matrix"),
    ("post", "/api/rbac/toggle"),
    ("get", "/api/rbac/users"),
    ("post", "/api/rbac/users/{target_id}/roles"),
    ("delete", "/api/rbac/users/{target_id}/roles/{role_code}"),
}


def test_root_reports_service_identity(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["health"] == "/health"
    assert "Patent" in body["name"]


def test_health_is_degraded_without_firebase_credentials(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_me_requires_a_bearer_token(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_rejects_a_garbage_token(client: TestClient) -> None:
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code in {401, 503}


def test_openapi_mounts_the_whole_frontend_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    mounted = {
        (method, path)
        for path, operations in schema["paths"].items()
        for method in operations
    }
    missing = sorted(CONTRACT_PATHS - mounted)
    assert not missing, f"missing from the API: {missing}"


def test_legacy_auth_endpoints_are_gone(client: TestClient) -> None:
    for path in ("/api/auth/refresh", "/api/auth/dev-login", "/api/auth/google/login"):
        assert client.post(path).status_code == 404


def test_rbac_catalog_is_consistent() -> None:
    assert len(ALL_ROLE_CODES) == 4
    assert len(ALL_PERMISSION_IDS) == 27
    catalog = matrix()
    assert {role["role_code"] for role in catalog["roles"]} == set(ALL_ROLE_CODES)
    assert len(catalog["permissions"]) == 27
    # Super Admin always holds everything and cannot be toggled.
    assert DEFAULT_GRANTS[1] == set(ALL_PERMISSION_IDS)
    super_admin_grants = {
        grant["permission_id"]
        for grant in catalog["grants"]
        if grant["role_id"] == 1
    }
    assert super_admin_grants == set(ALL_PERMISSION_IDS)


def test_every_report_type_is_known() -> None:
    assert set(REPORT_TYPE_NAMES) == {
        "patent_applications",
        "documents",
        "calendar_events",
        "users",
    }


def test_stub_draft_always_carries_the_warning() -> None:
    patent = {"invention_title": "Self-sealing widget"}
    questionnaire = {
        "invention_type": "Utility",
        "problem_statement": "Widgets leak.",
        "proposed_solution": "Add a gasket.",
    }
    for section in drafting.SECTION_TYPES:
        text, provider, model = drafting.generate_section(patent, questionnaire, section)
        assert provider == "stub"
        assert model is None
        assert drafting.DRAFT_WARNING in text
        assert "Self-sealing widget" in text or section == "CLAIMS"


def test_unknown_draft_section_is_rejected() -> None:
    try:
        drafting.generate_section({}, {}, "GLOSSARY")
    except drafting.AIGenerationError as exc:
        assert "GLOSSARY" in str(exc)
    else:  # pragma: no cover - the assert above is the real check
        raise AssertionError("expected AIGenerationError")


def test_builtin_docx_layout_renders_and_is_inspectable() -> None:
    patent = {"invention_title": "Self-sealing widget"}
    sections = {section: f"{section} body" for section in drafting.SECTION_TYPES}
    content = documents.render_docx(patent, sections, None)
    assert content.startswith(b"PK")
    assert len(content) > 5_000

    unknown, unused, parse_error = documents.inspect_template(content)
    assert parse_error is None
    assert unknown == []
    # The built-in layout contains no Jinja tags, so every known placeholder is
    # reported as unused.
    assert set(unused) == set(documents.KNOWN_PLACEHOLDERS)


def test_document_context_carries_the_watermark_and_title() -> None:
    context = documents.build_context(
        {"invention_title": "Self-sealing widget"}, {"ABSTRACT": "An abstract."}
    )
    assert context["TITLE"] == "Self-sealing widget"
    assert context["WATERMARK_TEXT"] == documents.WATERMARK_TEXT
    assert context["ABSTRACT"] == "An abstract."
    assert context["CLAIMS"] == "Not generated."


# ---------------------------------------------------------------------------
# Deployment limits
# ---------------------------------------------------------------------------


def test_capabilities_are_public_and_describe_the_limits(client: TestClient) -> None:
    response = client.get("/api/config/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "deployment_target",
        "max_upload_size_bytes",
        "max_request_body_bytes",
        "pdf_generation_enabled",
    }
    assert body["deployment_target"] in {"self_hosted", "vercel"}
    assert body["max_upload_size_bytes"] > 0
    assert body["max_request_body_bytes"] >= body["max_upload_size_bytes"]
    assert isinstance(body["pdf_generation_enabled"], bool)
    assert response.headers["cache-control"] == "no-store"


def test_upload_limit_zero_uses_the_profile_default() -> None:
    local = Settings(
        deployment_target="self_hosted", max_upload_size_bytes=0, _env_file=None
    )
    assert local.upload_limit_bytes == DEFAULT_SELF_HOSTED_UPLOAD_BYTES

    vercel = Settings(
        deployment_target="vercel", max_upload_size_bytes=0, _env_file=None
    )
    assert vercel.upload_limit_bytes == DEFAULT_VERCEL_UPLOAD_BYTES


def test_explicit_upload_limits_are_kept_off_vercel() -> None:
    settings = Settings(
        deployment_target="self_hosted",
        max_upload_size_bytes=2 * MIB,
        _env_file=None,
    )
    assert settings.upload_limit_bytes == 2 * MIB
    assert settings.request_body_limit_bytes == 2 * MIB + MULTIPART_OVERHEAD_BYTES

    # A lower explicit limit is a ceiling, not a value to raise to the cap.
    smaller = Settings(
        deployment_target="vercel",
        max_upload_size_bytes=1 * MIB,
        _env_file=None,
    )
    assert smaller.upload_limit_bytes == 1 * MIB


def test_vercel_profile_clamps_explicit_limits_below_the_body_cap() -> None:
    settings = Settings(
        deployment_target="vercel",
        max_upload_size_bytes=10 * MIB,
        _env_file=None,
    )
    assert settings.upload_limit_bytes == (
        VERCEL_BODY_LIMIT_BYTES - MULTIPART_OVERHEAD_BYTES
    )
    assert settings.request_body_limit_bytes == VERCEL_BODY_LIMIT_BYTES


def test_request_body_guard_rejects_oversized_uploads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    response = client.post(
        "/api/auth/sync",
        content=b"x" * (MULTIPART_OVERHEAD_BYTES * 2),
        headers={
            "Content-Type": "application/json",
            "Origin": "http://localhost:5173",
        },
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    # The guard must sit inside CORS, or the browser sees a CORS error
    # instead of the 413 detail.
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_wraps_host_rejections(client: TestClient) -> None:
    """TrustedHost must sit inside CORS so a browser can read its 400."""
    response = client.post(
        "/api/auth/sync",
        content=b"{}",
        headers={
            "Host": "evil.example.com",
            "Origin": "http://localhost:5173",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_security_headers_land_on_route_and_rejection_responses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = client.get("/")
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert ok.headers["x-frame-options"] == "DENY"
    assert ok.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "geolocation=()" in ok.headers["permissions-policy"]

    # The body guard rejects before routing, so this proves the header layer
    # wraps middleware-generated responses too, not just route responses.
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)

    def chunks():
        for _ in range(3):
            yield b"x" * MULTIPART_OVERHEAD_BYTES

    rejected = client.post(
        "/api/auth/sync",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert rejected.status_code == 413
    assert rejected.headers["x-content-type-options"] == "nosniff"


def test_unhandled_errors_stay_readable_by_the_browser(client: TestClient) -> None:
    from app.core import security
    from app.main import app

    def boom():
        raise RuntimeError("boom")

    app.dependency_overrides[security.current_user] = boom
    try:
        response = client.get(
            "/api/auth/me", headers={"Origin": "http://localhost:5173"}
        )
    finally:
        app.dependency_overrides.pop(security.current_user, None)

    assert response.status_code == 500
    assert response.json()["detail"].startswith("RuntimeError")
    # Starlette's own Exception handler runs outside user middleware. If the
    # catch-all regresses, the browser sees a CORS error instead of this body.
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_request_body_guard_counts_chunked_bodies(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)

    def chunks():
        for _ in range(3):
            yield b"x" * MULTIPART_OVERHEAD_BYTES

    response = client.post(
        "/api/auth/sync",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_read_upload_stops_one_chunk_past_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    upload = UploadFile(filename="big.bin", file=BytesIO(b"x" * 4096))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resources._read_upload(upload))
    assert exc.value.status_code == 413


def test_pdf_defaults_safely_per_deployment_target() -> None:
    vercel = Settings(deployment_target="vercel", _env_file=None)
    assert vercel.pdf_generation_enabled is False

    local = Settings(deployment_target="self_hosted", _env_file=None)
    assert local.pdf_generation_enabled is True

    # An explicit value overrides the profile in both directions.
    assert (
        Settings(
            deployment_target="vercel",
            pdf_conversion_enabled=True,
            _env_file=None,
        ).pdf_generation_enabled
        is True
    )
    assert (
        Settings(
            deployment_target="self_hosted",
            pdf_conversion_enabled=False,
            _env_file=None,
        ).pdf_generation_enabled
        is False
    )


def test_pdf_gate_rejects_pdf_when_conversion_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources
    from app.core.config import settings

    monkeypatch.setattr(settings, "pdf_conversion_enabled", False)
    with pytest.raises(HTTPException) as exc:
        resources._ensure_format_supported("PDF")
    assert exc.value.status_code == 400
    assert "DOCX" in str(exc.value.detail)

    # DOCX still works, and unknown formats stay rejected either way.
    resources._ensure_format_supported("DOCX")
    with pytest.raises(HTTPException):
        resources._ensure_format_supported("ODT")


def test_chunks_streams_and_closes_the_blob() -> None:
    from app.api import resources

    class FakeStream:
        def __init__(self, data: bytes) -> None:
            self.buffer = BytesIO(data)
            self.closed = False

        def read(self, size: int) -> bytes:
            return self.buffer.read(size)

        def close(self) -> None:
            self.closed = True

    stream = FakeStream(b"a" * 10)
    assert b"".join(resources._chunks(stream, chunk_size=4)) == b"a" * 10
    assert stream.closed


def test_capabilities_hide_pdf_when_libreoffice_is_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import resources

    monkeypatch.setattr(resources.docgen, "pdf_available", lambda: False)
    body = client.get("/api/config/capabilities").json()
    assert body["pdf_generation_enabled"] is False


def test_pdf_gate_reports_missing_libreoffice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import resources
    from app.core.config import settings

    monkeypatch.setattr(settings, "pdf_conversion_enabled", True)
    monkeypatch.setattr(resources.docgen, "pdf_available", lambda: False)
    with pytest.raises(HTTPException) as exc:
        resources._ensure_format_supported("PDF")
    assert exc.value.status_code == 400
    assert "LibreOffice" in str(exc.value.detail)


def test_inline_service_account_json_is_validated() -> None:
    from app.core import firebase
    from app.core.config import Settings

    assert firebase._credentials_from_json("") is None
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json("{not-json")
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json("[]")
    # Parsed JSON that is not a usable certificate also fails as configuration.
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json('{"type": "service_account"}')

    settings = Settings(
        firebase_service_account_json='{"private_key": "super-secret"}',
        _env_file=None,
    )
    assert "super-secret" not in repr(settings)


def test_download_filenames_cannot_break_headers() -> None:
    from app.api import resources

    cleaned = resources._clean_filename('report"\r\nX-Injected: 1.csv')
    assert cleaned == "report'  X-Injected: 1.csv"
    assert resources._clean_filename("../../etc/passwd") == "passwd"
    # Backslashes are separators on Windows even though PurePath on Linux
    # treats them as ordinary characters.
    assert "\\" not in resources._clean_filename(r"..\..\windows\system32\x.txt")


def test_download_filename_header_is_ascii_safe_for_any_script() -> None:
    from app.api import resources

    header = resources._content_disposition("特許 出願.docx")["Content-Disposition"]
    # Starlette encodes every header as Latin-1; a raw Unicode filename raises.
    header.encode("latin-1")
    assert 'filename="' in header
    assert "filename*=UTF-8''" in header
    assert "%E7%89%B9%E8%A8%B1" in header

    long_header = resources._content_disposition("a" * 400 + ".pdf")[
        "Content-Disposition"
    ]
    assert len(long_header) < 500
    assert ".pdf" in long_header


def test_report_cells_cannot_start_a_spreadsheet_formula() -> None:
    from app.api import resources

    assert resources._csv_safe('=HYPERLINK("http://evil", "click")').startswith("'=")
    assert resources._csv_safe("+1+1").startswith("'+")
    assert resources._csv_safe("@SUM(A1)").startswith("'@")
    assert resources._csv_safe("ordinary title") == "ordinary title"
    assert resources._csv_safe(None) == ""


def test_bootstrap_admin_requires_a_verified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import security
    from app.core.config import settings

    monkeypatch.setattr(settings, "bootstrap_admin_email", "owner@example.com")
    unverified = security._new_profile(
        "u1", {"email": "owner@example.com", "email_verified": False}
    )
    assert unverified["account_status"] == "pending"
    assert unverified["role_codes"] == ["INNOVATOR"]

    verified = security._new_profile(
        "u2", {"email": "owner@example.com", "email_verified": True}
    )
    assert verified["account_status"] == "approved"
    assert verified["role_codes"] == ["SUPER_ADMIN"]


def test_gemini_key_is_a_header_and_never_echoed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.services import drafting

    secret = "super-secret-key"
    monkeypatch.setattr(settings, "gemini_api_key", secret)
    seen: dict = {}

    def fake_post(url: str, **kwargs):
        seen.update(kwargs)
        request = httpx.Request("POST", f"{url}?key={secret}")
        raise httpx.HTTPStatusError(
            f"Client error '400 Bad Request' for url '{request.url}'",
            request=request,
            response=httpx.Response(400, request=request),
        )

    monkeypatch.setattr(drafting.httpx, "post", fake_post)
    with pytest.raises(drafting.AIGenerationError) as exc:
        drafting._gemini_text({"invention_title": "Test"}, {}, "ABSTRACT")

    assert secret not in str(exc.value)
    assert "key" not in seen
    assert seen["headers"]["x-goog-api-key"] == secret


def test_request_id_is_echoed_and_untrusted_values_are_replaced(
    client: TestClient,
) -> None:
    supplied = client.get(
        "/api/config/capabilities", headers={"X-Request-ID": "support-ticket-42"}
    )
    assert supplied.headers["x-request-id"] == "support-ticket-42"

    # A header value that could break logging or response headers is replaced
    # with a generated hex ID rather than reflected.
    hostile = client.get(
        "/api/config/capabilities", headers={"X-Request-ID": "bad value\r\nx: y"}
    )
    generated = hostile.headers["x-request-id"]
    assert generated != "bad value\r\nx: y"
    assert len(generated) == 32
    assert all(char in "0123456789abcdef" for char in generated)
