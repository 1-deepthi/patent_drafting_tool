"""Closes open item #36: the retry-creates-a-new-job SUCCESS path was the
one gap test_document_generation.py's test_retry_is_rejected_for_a_
completed_job explicitly flagged as untestable without a fault-injection
hook, since nothing in the stub-provider/local-storage setup can otherwise
force a real Failed document-generation job. Uses
tests.helpers.AlwaysFailStorageProvider (a StorageProvider test double
that always raises StorageError) monkeypatched into
app.api.documents.get_storage_provider for exactly the duration of one
call, to deterministically trigger the existing, already-correct
StorageError -> Failed-job path in run_generation_job(), then retries it
for real."""
import app.api.documents as documents_api
from tests.helpers import AlwaysFailStorageProvider, assign_and_accept_agent, create_submitted_patent


async def test_retry_creates_a_new_job_after_a_genuine_storage_failure(client, make_user, monkeypatch):
    innovator = await make_user("INNOVATOR", "innovator@retry-success-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@retry-success-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Retry Success Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)
    r = await client.post(f"/api/patents/{pid}/draft/generate", json={}, headers=agent)
    assert r.status_code == 200, r.text

    # Force the storage layer to fail for exactly this one call.
    monkeypatch.setattr(documents_api, "get_storage_provider", lambda: AlwaysFailStorageProvider())
    r = await client.post(
        f"/api/patents/{pid}/documents/generate", json={"output_format": "PDF"}, headers=agent
    )
    assert r.status_code == 200, r.text  # a Failed job is a normal response, not a 500
    failed_job = r.json()
    assert failed_job["status"] == "Failed", failed_job
    assert failed_job["error_message"], "Failed job should record why it failed"
    original_job_id = failed_job["id"]

    # Restore the real (working) storage provider before retrying.
    monkeypatch.undo()

    r = await client.post(f"/api/patents/{pid}/documents/jobs/{original_job_id}/retry", headers=agent)
    assert r.status_code == 200, r.text
    new_job = r.json()
    assert new_job["status"] == "Completed", new_job
    assert new_job["id"] != original_job_id
    assert new_job["retried_from_job_id"] == original_job_id

    # The original Failed job is untouched — preserved for audit/history,
    # per run_generation_job's own docstring, not overwritten by the retry.
    r = await client.get(f"/api/patents/{pid}/documents/jobs", headers=agent)
    assert r.status_code == 200
    jobs_by_id = {j["id"]: j for j in r.json()}
    assert jobs_by_id[original_job_id]["status"] == "Failed"
    assert jobs_by_id[new_job["id"]]["status"] == "Completed"

    # And the document is actually downloadable now, with real PDF bytes —
    # same standard the other document-generation test holds itself to.
    r = await client.get(f"/api/patents/{pid}/documents", headers=agent)
    document_id = r.json()[0]["id"]
    r = await client.get(f"/api/patents/{pid}/documents/{document_id}/download", headers=agent)
    assert r.status_code == 200
    assert r.content[:5] == b"%PDF-"


async def test_retry_still_rejected_if_storage_fails_again(client, make_user, monkeypatch):
    """Regression guard for the other half of the contract: retry is not a
    guaranteed fix — if the underlying problem is still present, the new
    job also comes back Failed rather than being forced to Completed."""
    innovator = await make_user("INNOVATOR", "innovator@retry-still-fails-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@retry-still-fails-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Retry Still Fails Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)
    await client.post(f"/api/patents/{pid}/draft/generate", json={}, headers=agent)

    monkeypatch.setattr(documents_api, "get_storage_provider", lambda: AlwaysFailStorageProvider())
    r = await client.post(
        f"/api/patents/{pid}/documents/generate", json={"output_format": "PDF"}, headers=agent
    )
    original_job_id = r.json()["id"]
    assert r.json()["status"] == "Failed"

    # Storage is still broken — don't undo the monkeypatch this time.
    r = await client.post(f"/api/patents/{pid}/documents/jobs/{original_job_id}/retry", headers=agent)
    assert r.status_code == 200, r.text
    retried = r.json()
    assert retried["status"] == "Failed"
    assert retried["retried_from_job_id"] == original_job_id
