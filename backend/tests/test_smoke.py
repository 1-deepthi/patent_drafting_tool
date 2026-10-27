"""Offline smoke tests: the app boots, the contract is mounted, and the
pure-Python services behave. No Firebase credentials are required.
"""
import asyncio
from io import BytesIO

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
    assert body["deployment_target"] in {"self_hosted", "vercel"}
    assert body["max_upload_size_bytes"] > 0
    assert body["max_request_body_bytes"] >= body["max_upload_size_bytes"]
    assert isinstance(body["pdf_generation_enabled"], bool)


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


def test_inline_service_account_json_is_validated() -> None:
    from app.core import firebase

    assert firebase._credentials_from_json("") is None
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json("{not-json")
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json("[]")
    # Parsed JSON that is not a usable certificate also fails as configuration.
    with pytest.raises(firebase.FirebaseNotConfigured):
        firebase._credentials_from_json('{"type": "service_account"}')
