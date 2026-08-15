"""Regression tests for the Notifications endpoints (§7.13/§10 open item #8
follow-up: click-tested manually in §7.11, never automated until now).
Per app/api/notifications.py's docstring, these are strictly user-scoped —
a user only ever sees/marks their own rows, never another user's, even by
guessing an id.

Note on baseline notifications: assign_and_accept_agent (tests/helpers.py)
performs a real assign, which itself fires an "Assigned" notification to
the agent (see app/services/patent_service.py). My first version of this
file assumed a clean inbox right after setup and hardcoded absolute counts
(0, then 1, then 2) — that failed, because the baseline is actually 1, not
0. That was my wrong assumption, not a bug: assign firing its own
notification is real, intentional behavior, separate from anything
comments do. Every test below reads the baseline unread-count right after
setup and asserts deltas from it, instead of hardcoding absolutes."""
from tests.helpers import assign_and_accept_agent, create_submitted_patent


async def _make_one_notification(client, innovator, agent, pid):
    """Posting a comment as the innovator produces exactly one CommentAdded
    notification for the agent (see test_comments.py) — reused here purely
    as a convenient, real way to get an additional notification row."""
    r = await client.post(
        f"/api/patents/{pid}/comments", json={"comment_text": "trigger"}, headers=innovator
    )
    assert r.status_code == 201, r.text


async def _unread_count(client, headers) -> int:
    r = await client.get("/api/notifications/unread-count", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["unread_count"]


async def test_list_notifications_and_unread_count(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@notif-list-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@notif-list-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Notif List Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)

    # Baseline after assign+accept: the agent already has one unread
    # "Assigned" notification.
    baseline = await _unread_count(client, agent)
    assert baseline == 1

    await _make_one_notification(client, innovator, agent, pid)

    r = await client.get("/api/notifications", headers=agent)
    assert r.status_code == 200
    notes = r.json()
    assert len(notes) == 2  # Assigned + CommentAdded
    assert r.headers["X-Total-Count"] == "2"
    assert any(n["notification_type"] == "CommentAdded" and not n["is_read"] for n in notes)

    assert await _unread_count(client, agent) == baseline + 1


async def test_mark_read_updates_is_read_and_unread_count(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@notif-markread-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@notif-markread-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Notif Mark Read Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)
    baseline = await _unread_count(client, agent)

    await _make_one_notification(client, innovator, agent, pid)
    assert await _unread_count(client, agent) == baseline + 1

    r = await client.get("/api/notifications", headers=agent)
    # Most recent first (created_at desc) -> the CommentAdded one is [0].
    notification_id = r.json()[0]["id"]

    r = await client.patch(f"/api/notifications/{notification_id}/read", headers=agent)
    assert r.status_code == 200, r.text
    assert r.json()["is_read"] is True

    # Back down to just the (still-unread) baseline notification.
    assert await _unread_count(client, agent) == baseline


async def test_mark_all_read(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@notif-markall-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@notif-markall-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Notif Mark All Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)
    baseline = await _unread_count(client, agent)

    # Two comments from the innovator -> two CommentAdded notifications for the agent.
    await _make_one_notification(client, innovator, agent, pid)
    await _make_one_notification(client, innovator, agent, pid)
    assert await _unread_count(client, agent) == baseline + 2

    r = await client.post("/api/notifications/read-all", headers=agent)
    assert r.status_code == 204

    assert await _unread_count(client, agent) == 0


async def test_user_cannot_read_or_mark_another_users_notification(client, make_user):
    """Regression guard: notifications are user-scoped in the endpoint
    logic (not just in the URL) — a user must not be able to view or mark
    read a row belonging to someone else, even with a guessed/known id."""
    innovator = await make_user("INNOVATOR", "innovator@notif-isolation-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@notif-isolation-test.dev")
    other_agent = await make_user("PATENT_AGENT", "other-agent@notif-isolation-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Notif Isolation Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)
    await _make_one_notification(client, innovator, agent, pid)

    r = await client.get("/api/notifications", headers=agent)
    notification_id = r.json()[0]["id"]

    # other_agent has no notifications of their own (never assigned
    # anything, no comment activity) and must not be able to touch the
    # one that belongs to `agent`.
    r = await client.get("/api/notifications", headers=other_agent)
    assert r.json() == []

    r = await client.patch(f"/api/notifications/{notification_id}/read", headers=other_agent)
    assert r.status_code == 404
