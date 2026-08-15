"""Regression tests for Calendar events (§7.13/§10 open item #8 follow-up:
click-tested manually in §7.11, never automated until now). Per
app/api/calendar.py's docstring, create/delete is restricted to the
assigned Patent Agent or an Admin/Super Admin — the same permission
model as document generation — while anyone who can view the application
may list its events. Also covers the cross-patent /api/calendar/events
'my upcoming events' view."""
from datetime import datetime, timedelta, timezone

from tests.helpers import assign_and_accept_agent, create_submitted_patent


def _future_iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def test_assigned_agent_can_create_list_and_delete_event(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@calendar-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@calendar-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Calendar Test Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)

    r = await client.post(
        f"/api/patents/{pid}/calendar-events",
        json={"event_type": "Filing Deadline", "event_date": _future_iso(30)},
        headers=agent,
    )
    assert r.status_code == 201, r.text
    event = r.json()
    assert event["event_type"] == "Filing Deadline"
    assert event["invention_title"] == "Calendar Test Widget"
    event_id = event["id"]

    # The innovator can see it too (visible to anyone who can view the
    # application), even though only the agent/admin can manage it.
    r = await client.get(f"/api/patents/{pid}/calendar-events", headers=innovator)
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    assert listed[0]["id"] == event_id

    r = await client.delete(f"/api/patents/{pid}/calendar-events/{event_id}", headers=agent)
    assert r.status_code == 204

    r = await client.get(f"/api/patents/{pid}/calendar-events", headers=innovator)
    assert r.json() == []


async def test_innovator_cannot_create_or_delete_events(client, make_user):
    """Regression guard: per the module docstring, only the assigned agent
    or an Admin/Super Admin may manage events — an Innovator (even the
    owning one, who CAN view/list) must be rejected on create/delete."""
    innovator = await make_user("INNOVATOR", "innovator@calendar-authz-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@calendar-authz-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Calendar Authz Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)

    r = await client.post(
        f"/api/patents/{pid}/calendar-events",
        json={"event_type": "Hearing", "event_date": _future_iso(10)},
        headers=innovator,
    )
    assert r.status_code == 403, r.text

    # Have the agent create one, then confirm the innovator can't delete it.
    r = await client.post(
        f"/api/patents/{pid}/calendar-events",
        json={"event_type": "Hearing", "event_date": _future_iso(10)},
        headers=agent,
    )
    event_id = r.json()["id"]

    r = await client.delete(f"/api/patents/{pid}/calendar-events/{event_id}", headers=innovator)
    assert r.status_code == 403


async def test_invalid_event_type_is_rejected(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@calendar-eventtype-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@calendar-eventtype-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Calendar Event Type Widget")
    await assign_and_accept_agent(client, innovator, agent, pid)

    r = await client.post(
        f"/api/patents/{pid}/calendar-events",
        json={"event_type": "Not A Real Type", "event_date": _future_iso(5)},
        headers=agent,
    )
    assert r.status_code == 422, r.text


async def test_cross_patent_calendar_scoped_to_visible_patents(client, make_user):
    """Covers the standalone /api/calendar/events 'my upcoming events' view:
    an agent should only see events for patents assigned to them, not every
    event in the system."""
    innovator = await make_user("INNOVATOR", "innovator@calendar-cross-test.dev")
    agent_a = await make_user("PATENT_AGENT", "agent_a@calendar-cross-test.dev")
    agent_b = await make_user("PATENT_AGENT", "agent_b@calendar-cross-test.dev")

    pid_a, _ = await create_submitted_patent(client, innovator, "Cross Calendar Widget A")
    await assign_and_accept_agent(client, innovator, agent_a, pid_a)
    r = await client.post(
        f"/api/patents/{pid_a}/calendar-events",
        json={"event_type": "Examination", "event_date": _future_iso(15)},
        headers=agent_a,
    )
    assert r.status_code == 201, r.text

    pid_b, _ = await create_submitted_patent(client, innovator, "Cross Calendar Widget B")
    await assign_and_accept_agent(client, innovator, agent_b, pid_b)
    r = await client.post(
        f"/api/patents/{pid_b}/calendar-events",
        json={"event_type": "Reminder", "event_date": _future_iso(20)},
        headers=agent_b,
    )
    assert r.status_code == 201, r.text

    r = await client.get("/api/calendar/events", headers=agent_a)
    assert r.status_code == 200
    titles = [e["invention_title"] for e in r.json()]
    assert titles == ["Cross Calendar Widget A"]

    # The innovator is on both teams, so they should see both.
    r = await client.get("/api/calendar/events", headers=innovator)
    titles = sorted(e["invention_title"] for e in r.json())
    assert titles == ["Cross Calendar Widget A", "Cross Calendar Widget B"]
