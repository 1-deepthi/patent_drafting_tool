"""Offline smoke tests: the app boots, the contract is mounted, and the
pure-Python services behave. No Firebase credentials are required.
"""
from fastapi.testclient import TestClient

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
