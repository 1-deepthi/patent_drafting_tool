"""Shared helpers for building test fixtures via real API calls (not direct
DB inserts) — this way every test also exercises the real endpoint chain,
the same standard the manual browser sessions held themselves to."""

from app.services.storage.base import StorageError, StorageProvider


class AlwaysFailStorageProvider(StorageProvider):
    """Fault-injection test double for StorageProvider — closes open item
    #36 ('no fault-injection hook exists for forcing a genuinely Failed
    document-generation job'). Every operation raises StorageError, which
    run_generation_job() already catches and turns into a real Failed
    DocumentGenerationJob row (see app/services/document_service.py) —
    this double doesn't change any production code, it just gives tests a
    deterministic way to trigger that existing, already-correct failure
    path, since nothing in the stub-provider/local-storage setup can
    otherwise force a real failure on demand."""

    name = "always-fail-test-double"

    async def save(self, *, key: str, content: bytes) -> str:
        raise StorageError("Injected failure for testing (AlwaysFailStorageProvider)")

    async def load(self, *, key: str) -> bytes:
        raise StorageError("Injected failure for testing (AlwaysFailStorageProvider)")

    async def delete(self, *, key: str) -> None:
        raise StorageError("Injected failure for testing (AlwaysFailStorageProvider)")


async def create_submitted_patent(client, innovator_headers, title="Test Widget"):
    """Creates a team + patent + applicant + inventor + completed
    questionnaire, submits it, and returns the patent id. Mirrors exactly
    the API sequence /home/claude/setup_data.py used for manual browser
    testing in Project_Handover_v10.md §7.12."""
    r = await client.post("/api/teams", json={"team_name": f"Team for {title}"}, headers=innovator_headers)
    assert r.status_code in (200, 201), r.text
    team_id = r.json()["id"]

    r = await client.post(
        "/api/patents", json={"team_id": team_id, "invention_title": title}, headers=innovator_headers
    )
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]

    r = await client.post(
        f"/api/patents/{pid}/applicants",
        json={
            "applicant_type": "Individual",
            "full_name_or_org_name": "Jane Doe",
            "country": "IN",
            "is_primary": True,
        },
        headers=innovator_headers,
    )
    assert r.status_code in (200, 201), r.text

    r = await client.post(
        f"/api/patents/{pid}/inventors",
        json={"full_name": "Jane Doe", "country": "IN"},
        headers=innovator_headers,
    )
    assert r.status_code in (200, 201), r.text

    r = await client.patch(
        f"/api/patents/{pid}/questionnaire",
        json={
            "invention_type": "Software",
            "problem_statement": "Existing systems are slow.",
            "proposed_solution": "A faster system using caching.",
            "novelty_description": "Novel caching layer.",
            "technical_description": "Uses a distributed cache with TTL eviction.",
            "advantages": "Faster response times.",
            "prior_art": "None found.",
            "keywords": "caching, performance",
            "has_existing_drawings": False,
        },
        headers=innovator_headers,
    )
    assert r.status_code == 200, r.text

    r = await client.post(f"/api/patents/{pid}/questionnaire/submit", headers=innovator_headers)
    assert r.status_code == 200, r.text

    r = await client.post(f"/api/patents/{pid}/submit", headers=innovator_headers)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Submitted"

    return pid, team_id


async def assign_and_accept_agent(client, innovator_headers, agent_headers, pid: int) -> int:
    """Assigns `pid` to the agent behind `agent_headers` and has them accept,
    moving the patent to 'Under Review' with that agent as the visible
    assigned agent. Returns the agent's user id. Used by tests (comments,
    calendar) that need a real assigned-and-accepted agent as a second
    legitimate participant, rather than re-deriving the assign/accept
    sequence already covered by test_assignment_workflow.py."""
    r = await client.get("/api/auth/me", headers=agent_headers)
    assert r.status_code == 200, r.text
    agent_id = r.json()["user"]["id"]

    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_id}, headers=innovator_headers
    )
    assert r.status_code == 200, r.text

    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_headers)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Under Review"

    return agent_id


def build_docx_bytes(paragraphs: list[str]) -> bytes:
    """Builds a minimal real .docx (via python-docx) with one paragraph of
    plain text per entry in `paragraphs` — used by test_templates.py to
    produce real files containing Jinja placeholders (e.g. "{{ TITLE }}")
    for upload, since docxtpl needs an actual .docx, not just bytes that
    look like one."""
    import io

    from docx import Document

    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()


async def create_pending_user(email: str, full_name: str = "Pending Test User") -> int:
    """Inserts (or resets) a genuinely Pending (not auto-Approved) user
    directly via SQL. dev-login always creates Approved accounts (see
    app/api/auth.py), so there is no API path that produces a Pending
    user in this dev/test setup — a real Pending account only exists
    after a first real Google sign-in, before Super Admin approval. This
    mirrors exactly how the manual Playwright session in
    Project_Handover_v10.md §7.12 tested the Pending Approvals screen.

    Upserts on email (matching dev-login's own idempotency) rather than
    plain-inserting: the `users` table is deliberately NOT truncated
    between tests (see conftest.py's _DATA_TABLES comment), so running
    the suite more than once in the same test-database session — or
    reusing an email across two tests — would otherwise hit a duplicate
    key error on `users_email_key`. Returns the user's id."""
    from sqlalchemy import text

    from tests.conftest import engine

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "INSERT INTO users (google_id, email, full_name, account_status, "
                "is_active, is_deleted) VALUES (:google_id, :email, :full_name, "
                "'Pending', true, false) "
                "ON CONFLICT (email) DO UPDATE SET account_status = 'Pending', "
                "is_deleted = false, approved_by = NULL, approved_at = NULL "
                "RETURNING id"
            ),
            {"google_id": f"pending-test-{email}", "email": email, "full_name": full_name},
        )
        return result.scalar_one()


async def _set_permission(
    client, super_admin_headers, role_code: str, permission_code: str, grant: bool
) -> None:
    r = await client.get("/api/rbac/matrix", headers=super_admin_headers)
    assert r.status_code == 200, r.text
    matrix = r.json()
    role_id = next(r["id"] for r in matrix["roles"] if r["role_code"] == role_code)
    permission_id = next(
        p["id"] for p in matrix["permissions"] if p["permission_code"] == permission_code
    )
    r = await client.post(
        f"/api/rbac/toggle?grant={'true' if grant else 'false'}",
        json={"role_id": role_id, "permission_id": permission_id},
        headers=super_admin_headers,
    )
    assert r.status_code == 200, r.text


async def grant_permission(client, super_admin_headers, role_code: str, permission_code: str) -> None:
    """Grants `permission_code` to `role_code` via the real
    POST /api/rbac/toggle endpoint (app/api/rbac.py) — used by
    test_reports.py to exercise the ordinary REPORTS_VIEW/REPORTS_DOWNLOAD
    RBAC gate before checking the finer-grained ReportPermission matrix.
    role_permissions isn't truncated between tests (see conftest.py's
    _DATA_TABLES comment), so callers should pair this with
    revoke_permission in a try/finally, matching test_admin_rbac.py's own
    toggle-back convention."""
    await _set_permission(client, super_admin_headers, role_code, permission_code, grant=True)


async def revoke_permission(client, super_admin_headers, role_code: str, permission_code: str) -> None:
    await _set_permission(client, super_admin_headers, role_code, permission_code, grant=False)


async def _set_report_permission(
    client, super_admin_headers, role_code: str, report_type: str, grant: bool
) -> None:
    matrix_resp = await client.get(
        "/api/reports/permissions/matrix", headers=super_admin_headers
    )
    assert matrix_resp.status_code == 200, matrix_resp.text
    roles = matrix_resp.json()["roles"]
    role_id = next(role["id"] for role in roles if role["role_code"] == role_code)

    toggle_resp = await client.post(
        f"/api/reports/permissions/toggle?grant={'true' if grant else 'false'}",
        json={"role_id": role_id, "report_type": report_type},
        headers=super_admin_headers,
    )
    assert toggle_resp.status_code == 200, toggle_resp.text


async def grant_report_permission(
    client, super_admin_headers, role_code: str, report_type: str
) -> None:
    """Grants download access for `report_type` to `role_code` via the real
    POST /api/reports/permissions/toggle endpoint (app/api/reports.py).
    report_permissions isn't truncated between tests either — pair with
    revoke_report_permission in a try/finally."""
    await _set_report_permission(client, super_admin_headers, role_code, report_type, grant=True)


async def revoke_report_permission(
    client, super_admin_headers, role_code: str, report_type: str
) -> None:
    await _set_report_permission(client, super_admin_headers, role_code, report_type, grant=False)
