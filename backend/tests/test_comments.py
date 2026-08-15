"""Regression tests for the Comments sub-tab (§7.13/§10 open item #8
follow-up: click-tested manually in §7.11, never automated until now).
Per app/api/comments.py's own docstring, Comment is deliberately
append-only — no update/delete endpoint exists or should exist — and
comment creation is expected to notify the *other* participants on the
patent (open item #28), never the commenter themselves."""
from tests.helpers import assign_and_accept_agent, create_submitted_patent


async def test_create_and_list_comments_round_trip(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@comments-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@comments-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Comments Test Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)

    r = await client.get(f"/api/patents/{pid}/comments", headers=innovator)
    assert r.status_code == 200
    assert r.json() == []
    assert r.headers["X-Total-Count"] == "0"

    r = await client.post(
        f"/api/patents/{pid}/comments", json={"comment_text": "First comment."}, headers=innovator
    )
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["comment_text"] == "First comment."
    assert first["user_full_name"]

    r = await client.post(
        f"/api/patents/{pid}/comments", json={"comment_text": "Reply from the agent."}, headers=agent
    )
    assert r.status_code == 201, r.text

    # The assigned agent can also see the thread — it's a shared discussion,
    # not scoped to whoever wrote each individual comment.
    r = await client.get(f"/api/patents/{pid}/comments", headers=agent)
    assert r.status_code == 200
    listed = r.json()
    assert r.headers["X-Total-Count"] == "2"
    assert len(listed) == 2
    # Ordered oldest-first (Comment.created_at.asc() in the endpoint).
    assert listed[0]["comment_text"] == "First comment."
    assert listed[1]["comment_text"] == "Reply from the agent."


async def test_comment_visibility_enforced_for_non_participant(client, make_user):
    """Regression guard: an agent with no relationship to this patent must
    not be able to read or post to its comment thread, mirroring the same
    visibility rule test_files.py already checks for Files."""
    owner = await make_user("INNOVATOR", "owner@comments-visibility-test.dev")
    outsider_agent = await make_user("PATENT_AGENT", "outsider@comments-visibility-test.dev")
    pid, _ = await create_submitted_patent(client, owner, "Private Comments Widget")

    r = await client.get(f"/api/patents/{pid}/comments", headers=outsider_agent)
    assert r.status_code in (403, 404)

    r = await client.post(
        f"/api/patents/{pid}/comments", json={"comment_text": "Snooping."}, headers=outsider_agent
    )
    assert r.status_code in (403, 404)


async def test_comment_notifies_other_participants_but_not_the_author(client, make_user):
    """Encodes open item #28's actual implementation: posting a comment
    notifies the patent's innovator and assigned agent, excluding whoever
    just posted it (see comments.py::_notify_other_participants).

    Note: assign_and_accept_agent itself already leaves the agent with one
    unread "Assigned" notification (app/services/patent_service.py fires
    that on assign) before any comment happens -- my first version of this
    test assumed a clean inbox and asserted len(notes) == 1, which failed.
    That's not a bug; it's real, intentional notification behavior on the
    assign step, not just on comments. Filtering to CommentAdded
    specifically keeps this test scoped to comments only."""
    innovator = await make_user("INNOVATOR", "innovator@comments-notify-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@comments-notify-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Comments Notify Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)

    r = await client.post(
        f"/api/patents/{pid}/comments", json={"comment_text": "Status update."}, headers=innovator
    )
    assert r.status_code == 201, r.text

    # Author (innovator) should NOT get a CommentAdded notification for
    # their own comment.
    r = await client.get("/api/notifications", headers=innovator)
    innovator_comment_notes = [n for n in r.json() if n["notification_type"] == "CommentAdded"]
    assert innovator_comment_notes == []

    # The other participant (assigned agent) should get exactly one
    # CommentAdded notification, on top of whatever assign/accept already
    # produced for them.
    r = await client.get("/api/notifications", headers=agent)
    comment_notes = [n for n in r.json() if n["notification_type"] == "CommentAdded"]
    assert len(comment_notes) == 1
    assert comment_notes[0]["patent_application_id"] == pid


async def test_comments_have_no_update_or_delete_endpoint(client, make_user):
    """Regression guard for the deliberate append-only design stated in
    comments.py's module docstring: no PATCH/PUT/DELETE route should exist
    for an individual comment."""
    innovator = await make_user("INNOVATOR", "innovator@comments-immutable-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Immutable Comments Widget")

    r = await client.post(
        f"/api/patents/{pid}/comments", json={"comment_text": "Can't touch this."}, headers=innovator
    )
    comment_id = r.json()["id"]

    r = await client.patch(
        f"/api/patents/{pid}/comments/{comment_id}",
        json={"comment_text": "edited"},
        headers=innovator,
    )
    assert r.status_code in (404, 405)

    r = await client.delete(f"/api/patents/{pid}/comments/{comment_id}", headers=innovator)
    assert r.status_code in (404, 405)


async def test_comment_text_length_validation(client, make_user):
    """CommentCreate enforces min_length=1 — an empty comment should be
    rejected at the schema level (422), not silently accepted."""
    innovator = await make_user("INNOVATOR", "innovator@comments-validation-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Comment Validation Widget")

    r = await client.post(f"/api/patents/{pid}/comments", json={"comment_text": ""}, headers=innovator)
    assert r.status_code == 422
