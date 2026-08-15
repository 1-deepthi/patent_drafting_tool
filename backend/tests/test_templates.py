"""Regression tests for the Templates endpoints (app/api/templates.py),
which had zero test coverage until this file — discovered while closing
open item #31 ("in-UI placeholder validation for Templates"). Covers the
new validate_template_placeholders() behavior plus the pre-existing
upload/activate/delete/RBAC surface that was never automated."""
from tests.helpers import build_docx_bytes

_DOCUMENT_TYPE = "PATENT_APPLICATION"


def _upload_url(document_type: str = _DOCUMENT_TYPE, activate: bool = True) -> str:
    return f"/api/templates?document_type={document_type}&activate={str(activate).lower()}"


async def test_upload_with_all_known_placeholders_has_no_warnings(client, make_user):
    admin = await make_user("ADMIN", "admin@templates-clean-test.dev")
    content = build_docx_bytes(
        [
            "{{ TITLE }}",
            "{{ WATERMARK_TEXT }}",
            "{{ ABSTRACT }}",
            "{{ BACKGROUND }}",
            "{{ SUMMARY }}",
            "{{ DESCRIPTION }}",
            "{{ CLAIMS }}",
        ]
    )

    r = await client.post(
        _upload_url(),
        files={"upload": ("clean_template.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["unknown_placeholders"] == []
    assert body["unused_known_placeholders"] == []
    assert body["template_parse_error"] is None
    assert body["is_active"] is True


async def test_upload_with_unknown_placeholder_is_flagged_but_still_accepted(client, make_user):
    """Encodes open item #31's actual purpose: a misspelled/unsupported
    placeholder (e.g. a typo of {{ CLAIMS }}) must not silently disappear
    — the upload should still succeed (a bad template must never block
    document generation, per document_service.py's own design), but the
    response should flag it so the admin finds out immediately instead of
    only at generation time via a silent fallback."""
    admin = await make_user("ADMIN", "admin@templates-unknown-test.dev")
    content = build_docx_bytes(["{{ TITLE }}", "{{ CLAMS }}"])  # typo of CLAIMS

    r = await client.post(
        _upload_url(),
        files={"upload": ("typo_template.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["unknown_placeholders"] == ["CLAMS"]
    assert "WATERMARK_TEXT" in body["unused_known_placeholders"]
    assert body["template_parse_error"] is None


async def test_upload_of_unparseable_template_is_flagged_but_still_accepted(client, make_user):
    """A .docx that isn't valid Jinja-in-DOCX at all (e.g. an unterminated
    {% if %} block) can't be inspected for placeholders — the upload still
    succeeds (same reasoning as the unknown-placeholder case), but
    template_parse_error should explain why, matching build_docx_bytes()'s
    real fallback-to-plain-layout behavior at generation time."""
    admin = await make_user("ADMIN", "admin@templates-unparseable-test.dev")
    content = build_docx_bytes(["{% if x %}unterminated block, no matching endif"])

    r = await client.post(
        _upload_url(),
        files={"upload": ("broken_template.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["template_parse_error"] is not None
    assert body["unknown_placeholders"] is None or body["unknown_placeholders"] == []


async def test_only_admin_or_super_admin_can_upload(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@templates-rbac-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@templates-rbac-test.dev")
    content = build_docx_bytes(["{{ TITLE }}"])

    for headers in (innovator, agent):
        r = await client.post(
            _upload_url(),
            files={"upload": ("nope.docx", content, "application/vnd.openxmlformats")},
            headers=headers,
        )
        assert r.status_code == 403, r.text


async def test_non_docx_extension_is_rejected(client, make_user):
    admin = await make_user("ADMIN", "admin@templates-ext-test.dev")

    r = await client.post(
        _upload_url(),
        files={"upload": ("template.pdf", b"not a docx", "application/pdf")},
        headers=admin,
    )
    assert r.status_code == 422, r.text


async def test_new_upload_deactivates_previous_active_version(client, make_user):
    admin = await make_user("ADMIN", "admin@templates-version-test.dev")
    content = build_docx_bytes(["{{ TITLE }}"])

    r = await client.post(
        _upload_url(),
        files={"upload": ("v1.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    v1 = r.json()
    assert v1["version_number"] == 1
    assert v1["is_active"] is True

    r = await client.post(
        _upload_url(),
        files={"upload": ("v2.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    v2 = r.json()
    assert v2["version_number"] == 2
    assert v2["is_active"] is True

    r = await client.get(f"/api/templates?document_type={_DOCUMENT_TYPE}", headers=admin)
    by_id = {t["id"]: t for t in r.json()}
    assert by_id[v1["id"]]["is_active"] is False
    assert by_id[v2["id"]]["is_active"] is True
    # Listing (as opposed to the upload response itself) never carries
    # validation fields — those are upload-time-only, per TemplateOut's
    # own docstring.
    assert by_id[v1["id"]]["unknown_placeholders"] is None


async def test_activate_reactivates_an_older_version(client, make_user):
    admin = await make_user("ADMIN", "admin@templates-activate-test.dev")
    content = build_docx_bytes(["{{ TITLE }}"])

    r = await client.post(
        _upload_url(),
        files={"upload": ("v1.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    v1_id = r.json()["id"]
    r = await client.post(
        _upload_url(),
        files={"upload": ("v2.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    v2_id = r.json()["id"]

    r = await client.post(f"/api/templates/{v1_id}/activate", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True

    r = await client.get(f"/api/templates?document_type={_DOCUMENT_TYPE}", headers=admin)
    by_id = {t["id"]: t for t in r.json()}
    assert by_id[v1_id]["is_active"] is True
    assert by_id[v2_id]["is_active"] is False


async def test_delete_removes_a_non_active_version(client, make_user):
    admin = await make_user("ADMIN", "admin@templates-delete-test.dev")
    content = build_docx_bytes(["{{ TITLE }}"])

    r = await client.post(
        _upload_url(),
        files={"upload": ("v1.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    v1_id = r.json()["id"]
    await client.post(
        _upload_url(),
        files={"upload": ("v2.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )

    r = await client.delete(f"/api/templates/{v1_id}", headers=admin)
    assert r.status_code == 204

    r = await client.get(f"/api/templates?document_type={_DOCUMENT_TYPE}", headers=admin)
    ids = [t["id"] for t in r.json()]
    assert v1_id not in ids


async def test_unknown_document_type_is_rejected(client, make_user):
    admin = await make_user("ADMIN", "admin@templates-doctype-test.dev")
    content = build_docx_bytes(["{{ TITLE }}"])

    r = await client.post(
        _upload_url(document_type="NOT_A_REAL_TYPE"),
        files={"upload": ("v1.docx", content, "application/vnd.openxmlformats")},
        headers=admin,
    )
    assert r.status_code == 422, r.text
