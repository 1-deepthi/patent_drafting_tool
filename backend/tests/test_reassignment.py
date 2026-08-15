"""Tests for POST /{patent_id}/reassign — the post-acceptance Admin
override closing open item #7 (see the docstring on
test_can_assign_agent_even_before_submission_but_not_after_acceptance in
test_assignment_workflow.py for the exact gap this closes). Per spec item
12, this still can't let an Admin accept/reject on an agent's behalf — the
new agent lands in "Awaiting Patent Agent Acceptance" and must go through
the normal assignment/accept or assignment/reject endpoints themselves."""
from tests.helpers import assign_and_accept_agent, create_submitted_patent


async def test_admin_can_reassign_an_accepted_patent_to_a_new_agent(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@reassign2-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign2-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@reassign2-test.dev")
    admin_h = await make_user("ADMIN", "admin@reassign2-test.dev")
    agent_a_id = (await client.get("/api/auth/me", headers=agent_a_h)).json()["user"]["id"]
    agent_b_id = (await client.get("/api/auth/me", headers=agent_b_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Admin Reassign Widget")
    await assign_and_accept_agent(client, innovator, agent_a_h, pid)

    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_b_id, "reason": "Agent A went unresponsive."},
        headers=admin_h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["application_status"] == "Awaiting Patent Agent Acceptance"
    assert body["assigned_patent_agent_id"] == agent_b_id

    # New agent still has to accept it themselves — an admin can't do this
    # for them (spec item 12).
    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_b_h)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Under Review"
    assert r.json()["assigned_patent_agent_id"] == agent_b_id


async def test_reassign_requires_a_reason(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@reassign-reason-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign-reason-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@reassign-reason-test.dev")
    admin_h = await make_user("ADMIN", "admin@reassign-reason-test.dev")
    agent_b_id = (await client.get("/api/auth/me", headers=agent_b_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Reason Required Widget")
    await assign_and_accept_agent(client, innovator, agent_a_h, pid)

    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_b_id, "reason": ""},
        headers=admin_h,
    )
    assert r.status_code == 422, r.text


async def test_reassign_is_admin_only_not_available_to_innovator_or_agent(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@reassign-authz-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign-authz-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@reassign-authz-test.dev")
    agent_b_id = (await client.get("/api/auth/me", headers=agent_b_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Authz Reassign Widget")
    await assign_and_accept_agent(client, innovator, agent_a_h, pid)

    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_b_id, "reason": "Testing authz."},
        headers=innovator,
    )
    assert r.status_code == 403, r.text

    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_b_id, "reason": "Testing authz."},
        headers=agent_a_h,
    )
    assert r.status_code == 403, r.text


async def test_reassign_rejects_pre_acceptance_patents(client, make_user):
    """Before any agent has accepted, /assign or /auto-assign is the
    correct endpoint — /reassign should refuse and point that out rather
    than silently doing the same thing two different ways."""
    innovator = await make_user("INNOVATOR", "innovator@reassign-preacc-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign-preacc-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@reassign-preacc-test.dev")
    admin_h = await make_user("ADMIN", "admin@reassign-preacc-test.dev")
    agent_a_id = (await client.get("/api/auth/me", headers=agent_a_h)).json()["user"]["id"]
    agent_b_id = (await client.get("/api/auth/me", headers=agent_b_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Pre-Acceptance Widget")

    # Still "Submitted" — not assigned to anyone yet.
    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_a_id, "reason": "Testing."},
        headers=admin_h,
    )
    assert r.status_code == 400, r.text

    # Assigned but not yet accepted ("Awaiting Patent Agent Acceptance").
    await client.post(f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_a_id}, headers=innovator)
    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_b_id, "reason": "Testing."},
        headers=admin_h,
    )
    assert r.status_code == 400, r.text


async def test_reassign_rejects_same_agent(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@reassign-same-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign-same-test.dev")
    admin_h = await make_user("ADMIN", "admin@reassign-same-test.dev")

    pid, _ = await create_submitted_patent(client, innovator, "Same Agent Widget")
    agent_a_id = await assign_and_accept_agent(client, innovator, agent_a_h, pid)

    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_a_id, "reason": "Typo — meant someone else."},
        headers=admin_h,
    )
    assert r.status_code == 400, r.text


async def test_reassign_notifies_both_old_and_new_agent(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@reassign-notify-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign-notify-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@reassign-notify-test.dev")
    admin_h = await make_user("ADMIN", "admin@reassign-notify-test.dev")
    agent_b_id = (await client.get("/api/auth/me", headers=agent_b_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Notify Widget")
    await assign_and_accept_agent(client, innovator, agent_a_h, pid)

    await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_b_id, "reason": "Reassigning for workload balance."},
        headers=admin_h,
    )

    r = await client.get("/api/notifications", headers=agent_a_h)
    assert r.status_code == 200, r.text
    types_a = [n["notification_type"] for n in r.json()]
    assert "Reassigned" in types_a

    r = await client.get("/api/notifications", headers=agent_b_h)
    assert r.status_code == 200, r.text
    types_b = [n["notification_type"] for n in r.json()]
    assert "Assigned" in types_b


async def test_reassign_rejects_terminal_status(client, make_user):
    """A Granted/Rejected/Withdrawn/Abandoned application has no active
    work left to hand off — /reassign should refuse."""
    innovator = await make_user("INNOVATOR", "innovator@reassign-terminal-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign-terminal-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@reassign-terminal-test.dev")
    admin_h = await make_user("ADMIN", "admin@reassign-terminal-test.dev")
    agent_b_id = (await client.get("/api/auth/me", headers=agent_b_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Terminal Widget")
    await assign_and_accept_agent(client, innovator, agent_a_h, pid)

    # Force it to a terminal status directly for the purposes of this test
    # — there's no public endpoint to reach "Withdrawn" yet, and that's
    # not what this test is checking.
    from sqlalchemy import update
    from app.models import PatentApplication
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(PatentApplication).where(PatentApplication.id == pid).values(application_status="Withdrawn")
        )
        await session.commit()

    r = await client.post(
        f"/api/patents/{pid}/reassign",
        json={"patent_agent_id": agent_b_id, "reason": "Testing."},
        headers=admin_h,
    )
    assert r.status_code == 400, r.text
