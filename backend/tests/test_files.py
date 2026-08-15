"""Regression tests for the Files sub-tab round-trip, encoding the manual
Playwright test from Project_Handover_v10.md §7.12: upload -> verify
listing -> download and check actual bytes match -> delete -> verify
gone from both the list and disk."""
from tests.helpers import create_submitted_patent


async def test_upload_list_download_delete_round_trip(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@files-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Files Test Widget")

    r = await client.get(f"/api/patents/{pid}/files", headers=innovator)
    assert r.status_code == 200
    assert r.json() == []

    content = b"This is a test upload file for the Files sub-tab round trip."
    r = await client.post(
        f"/api/patents/{pid}/files",
        files={"upload": ("test_upload.txt", content, "text/plain")},
        headers=innovator,
    )
    assert r.status_code == 201, r.text
    uploaded = r.json()
    assert uploaded["original_file_name"] == "test_upload.txt"
    assert uploaded["file_size_bytes"] == len(content)
    file_id = uploaded["id"]

    r = await client.get(f"/api/patents/{pid}/files", headers=innovator)
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    assert listed[0]["id"] == file_id

    r = await client.get(f"/api/patents/{pid}/files/{file_id}/download", headers=innovator)
    assert r.status_code == 200
    # The actual bytes, not just a 200 — same standard §7.11/§7.12 held the
    # manual PDF-merge and file-download checks to.
    assert r.content == content

    r = await client.delete(f"/api/patents/{pid}/files/{file_id}", headers=innovator)
    assert r.status_code == 204

    r = await client.get(f"/api/patents/{pid}/files", headers=innovator)
    assert r.json() == []

    r = await client.get(f"/api/patents/{pid}/files/{file_id}/download", headers=innovator)
    assert r.status_code == 404


async def test_blocked_extension_is_rejected(client, make_user):
    """Regression guard for the spec'd upload block-list
    (blocked_upload_extensions in app/core/config.py)."""
    innovator = await make_user("INNOVATOR", "innovator@blocked-ext-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Blocked Ext Widget")

    r = await client.post(
        f"/api/patents/{pid}/files",
        files={"upload": ("malware.exe", b"fake binary content", "application/octet-stream")},
        headers=innovator,
    )
    assert r.status_code == 422, r.text


async def test_file_upload_requires_patent_visibility(client, make_user):
    """Regression guard: an unrelated Innovator (no team membership on this
    patent) must not be able to upload to or list someone else's files."""
    owner = await make_user("INNOVATOR", "owner@files-visibility-test.dev")
    outsider = await make_user("INNOVATOR", "outsider@files-visibility-test.dev")
    pid, _ = await create_submitted_patent(client, owner, "Private Widget")

    r = await client.get(f"/api/patents/{pid}/files", headers=outsider)
    assert r.status_code in (403, 404)

    r = await client.post(
        f"/api/patents/{pid}/files",
        files={"upload": ("sneaky.txt", b"hi", "text/plain")},
        headers=outsider,
    )
    assert r.status_code in (403, 404)


async def test_uploader_can_delete_own_file(client, make_user):
    """Confirms the widened file-delete permission noted as open item #27
    in the handover: uploader (not just Admin) can delete their own file."""
    innovator = await make_user("INNOVATOR", "innovator@delete-perm-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Delete Perm Widget")

    r = await client.post(
        f"/api/patents/{pid}/files",
        files={"upload": ("mine.txt", b"my file", "text/plain")},
        headers=innovator,
    )
    file_id = r.json()["id"]

    r = await client.delete(f"/api/patents/{pid}/files/{file_id}", headers=innovator)
    assert r.status_code == 204
