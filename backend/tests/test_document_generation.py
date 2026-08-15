"""Regression tests for the AI drafting + document generation pipeline.

test_generate_pdf_document_end_to_end is the highest-value test in this
suite: it drives the exact code path (run_generation_job() in
app/services/document_service.py) that had a real NameError bug, found
only by a live browser click-through in Project_Handover_v9.md §7.11 and
fixed in the "-updated" zip. That bug silently broke every document
regeneration and was masked in the browser as an unrelated-looking CORS
error — exactly the kind of thing a fast automated test should have
caught immediately instead of requiring a manual Playwright session to
discover. This test would have failed loudly on that bug.
"""
from tests.helpers import create_submitted_patent


async def _advance_to_under_review(client, innovator, agent_headers, agent_id, pid):
    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_id}, headers=innovator
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_headers)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Under Review"


async def test_generate_pdf_document_end_to_end(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@docgen-test.dev")
    agent_h = await make_user("PATENT_AGENT", "agent@docgen-test.dev")
    agent_id = (await client.get("/api/auth/me", headers=agent_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Docgen Test Widget")
    await _advance_to_under_review(client, innovator, agent_h, agent_id, pid)

    # Generate the AI draft (stub provider — offline-safe, no Gemini call)
    r = await client.post(f"/api/patents/{pid}/draft/generate", json={}, headers=agent_h)
    assert r.status_code == 200, r.text
    draft = r.json()
    assert len(draft["outputs"]) > 0

    # Generate the actual document — this is the call that hit the
    # NameError bug in §7.11.
    r = await client.post(
        f"/api/patents/{pid}/documents/generate",
        json={"output_format": "PDF"},
        headers=agent_h,
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "Completed", (
        f"Document generation job did not complete — this is exactly the failure mode "
        f"the §7.11 NameError bug produced. Job: {job}"
    )

    # Confirm the patent's status auto-advanced, per the documented behavior
    # in app/api/documents.py.
    r = await client.get(f"/api/patents/{pid}", headers=agent_h)
    assert r.json()["application_status"] == "Draft Generated"

    # Confirm a real Document + DocumentVersion exist and are downloadable
    # with real, non-empty PDF bytes — not just a 200 with an empty body.
    r = await client.get(f"/api/patents/{pid}/documents", headers=agent_h)
    assert r.status_code == 200
    documents = r.json()
    assert len(documents) == 1
    document_id = documents[0]["id"]

    r = await client.get(f"/api/patents/{pid}/documents/{document_id}/download", headers=agent_h)
    assert r.status_code == 200
    assert len(r.content) > 100, "Downloaded PDF is suspiciously small/empty"
    assert r.content[:5] == b"%PDF-", "Downloaded file is not a real PDF"


async def test_generate_docx_document_allowed_for_agent_but_not_innovator(client, make_user):
    """Regression guard for open item #21: DOCX output restricted to
    Patent Agent, Admin/Innovator limited to PDF."""
    innovator = await make_user("INNOVATOR", "innovator@docx-perm-test.dev")
    agent_h = await make_user("PATENT_AGENT", "agent@docx-perm-test.dev")
    agent_id = (await client.get("/api/auth/me", headers=agent_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Docx Perm Widget")
    await _advance_to_under_review(client, innovator, agent_h, agent_id, pid)
    await client.post(f"/api/patents/{pid}/draft/generate", json={}, headers=agent_h)

    r = await client.post(
        f"/api/patents/{pid}/documents/generate",
        json={"output_format": "DOCX"},
        headers=agent_h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Completed"

    r = await client.post(
        f"/api/patents/{pid}/documents/generate",
        json={"output_format": "DOCX"},
        headers=innovator,
    )
    assert r.status_code == 403, r.text


async def test_cannot_generate_documents_before_ai_draft_exists(client, make_user):
    """Regression guard for can_generate_documents' gating — matches the
    documented behavior that a job is never created for an ineligible
    patent (see run_generation_job's own docstring)."""
    innovator = await make_user("INNOVATOR", "innovator@no-draft-test.dev")
    agent_h = await make_user("PATENT_AGENT", "agent@no-draft-test.dev")
    agent_id = (await client.get("/api/auth/me", headers=agent_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "No Draft Widget")
    await _advance_to_under_review(client, innovator, agent_h, agent_id, pid)
    # Deliberately skip /draft/generate this time.

    r = await client.post(
        f"/api/patents/{pid}/documents/generate",
        json={"output_format": "PDF"},
        headers=agent_h,
    )
    assert r.status_code == 400, (
        f"Expected document generation to be rejected with no AI draft yet, got {r.status_code}: {r.text}"
    )

    # And confirm no job row was created for the rejected attempt.
    r = await client.get(f"/api/patents/{pid}/documents/jobs", headers=agent_h)
    assert r.json() == []


async def test_retry_is_rejected_for_a_completed_job(client, make_user):
    """Regression guard matching the endpoint's actual contract
    (app/api/documents.py: 'Only a Failed job can be retried') — retry
    exists to recover from a Failed run, not to force a fresh regeneration
    of something that already succeeded. The "retry creates a new job"
    success path (needing a genuinely Failed job) is now covered
    separately in test_document_generation_retry.py via a fault-injection
    storage double, closing what was previously open item #36."""
    innovator = await make_user("INNOVATOR", "innovator@retry-test.dev")
    agent_h = await make_user("PATENT_AGENT", "agent@retry-test.dev")
    agent_id = (await client.get("/api/auth/me", headers=agent_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Retry Test Widget")
    await _advance_to_under_review(client, innovator, agent_h, agent_id, pid)
    await client.post(f"/api/patents/{pid}/draft/generate", json={}, headers=agent_h)

    r = await client.post(
        f"/api/patents/{pid}/documents/generate", json={"output_format": "PDF"}, headers=agent_h
    )
    assert r.json()["status"] == "Completed"
    first_job_id = r.json()["id"]

    r = await client.post(
        f"/api/patents/{pid}/documents/jobs/{first_job_id}/retry", headers=agent_h
    )
    assert r.status_code == 400, (
        f"Expected retrying a Completed job to be rejected, got {r.status_code}: {r.text}"
    )
