"""Regression tests for the assignment state machine. This is exactly the
scenario that was hand-verified via Playwright in
Project_Handover_v10.md §7.12 (Reject -> reassign -> accept) — encoded
here so it's checked on every run instead of only when someone remembers
to click through it by hand again."""
from tests.helpers import create_submitted_patent


async def _get(client, headers, pid):
    r = await client.get(f"/api/patents/{pid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_assign_to_agent_moves_to_awaiting_acceptance(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@wf-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@wf-test.dev")
    r = await client.get("/api/auth/me", headers=agent_a_h)
    agent_a_id = r.json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Assign Test Widget")

    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_a_id}, headers=innovator
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["application_status"] == "Awaiting Patent Agent Acceptance"
    assert body["assigned_patent_agent_id"] == agent_a_id


async def test_reject_releases_assignment_back_to_submitted(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@reject-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reject-test.dev")
    r = await client.get("/api/auth/me", headers=agent_a_h)
    agent_a_id = r.json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Reject Test Widget")
    await client.post(f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_a_id}, headers=innovator)

    r = await client.post(
        f"/api/patents/{pid}/assignment/reject",
        json={"reason": "Workload too high right now."},
        headers=agent_a_h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # This is the exact state transition manually verified in §7.12: reject
    # must fully release the assignment, not leave it dangling.
    assert body["application_status"] == "Submitted"
    assert body["assigned_patent_agent_id"] is None


async def test_rejected_patent_can_be_reassigned_to_a_different_agent_and_accepted(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@reassign-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@reassign-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@reassign-test.dev")
    agent_a_id = (await client.get("/api/auth/me", headers=agent_a_h)).json()["user"]["id"]
    agent_b_id = (await client.get("/api/auth/me", headers=agent_b_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Reassign Test Widget")
    await client.post(f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_a_id}, headers=innovator)
    await client.post(
        f"/api/patents/{pid}/assignment/reject", json={"reason": "Too busy."}, headers=agent_a_h
    )

    # Reassign to Agent B, not Agent A again — mirrors the manual test exactly.
    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_b_id}, headers=innovator
    )
    assert r.status_code == 200, r.text
    assert r.json()["assigned_patent_agent_id"] == agent_b_id
    assert r.json()["application_status"] == "Awaiting Patent Agent Acceptance"

    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_b_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["application_status"] == "Under Review"
    assert body["assigned_patent_agent_id"] == agent_b_id


async def test_agent_a_no_longer_sees_patent_after_rejecting_it(client, make_user):
    """Regression guard: after Agent A rejects, it must not still appear in
    their 'awaiting your decision' queue (list_patents scoped to them)."""
    innovator = await make_user("INNOVATOR", "innovator@queue-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@queue-test.dev")
    agent_a_id = (await client.get("/api/auth/me", headers=agent_a_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Queue Test Widget")
    await client.post(f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_a_id}, headers=innovator)

    r = await client.get("/api/patents", headers=agent_a_h)
    titles_before = [p["invention_title"] for p in r.json()]
    assert "Queue Test Widget" in titles_before

    await client.post(
        f"/api/patents/{pid}/assignment/reject", json={"reason": "test"}, headers=agent_a_h
    )

    r = await client.get("/api/patents", headers=agent_a_h)
    titles_after = [p["invention_title"] for p in r.json()]
    assert "Queue Test Widget" not in titles_after


async def test_only_the_assigned_agent_can_accept_or_reject(client, make_user):
    """Regression guard: Agent B must not be able to accept/reject an
    assignment that belongs to Agent A."""
    innovator = await make_user("INNOVATOR", "innovator@authz-test.dev")
    agent_a_h = await make_user("PATENT_AGENT", "agent_a@authz-test.dev")
    agent_b_h = await make_user("PATENT_AGENT", "agent_b@authz-test.dev")
    agent_a_id = (await client.get("/api/auth/me", headers=agent_a_h)).json()["user"]["id"]

    pid, _ = await create_submitted_patent(client, innovator, "Authz Test Widget")
    await client.post(f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_a_id}, headers=innovator)

    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_b_h)
    assert r.status_code in (403, 404)

    r = await client.post(
        f"/api/patents/{pid}/assignment/reject", json={"reason": "test"}, headers=agent_b_h
    )
    assert r.status_code in (403, 404)


async def test_can_assign_agent_even_before_submission_but_not_after_acceptance(client, make_user):
    """Documents the actual, intentional design: PRE_ASSIGNMENT_STATUSES
    (app/services/patent_service.py) deliberately includes "Draft" so an
    agent can be brought on early, before the innovator formally submits.
    The real gate is AFTER an agent has accepted (Under Review) — that's
    when assign/auto-assign must be rejected, since reassignment at that
    point has to go through a different path (open item #7 in the
    handover: "no post-acceptance Admin reassignment" is still an open
    design question, not yet built)."""
    innovator = await make_user("INNOVATOR", "innovator@draft-gate-test.dev")
    agent_h = await make_user("PATENT_AGENT", "agent@draft-gate-test.dev")
    agent_id = (await client.get("/api/auth/me", headers=agent_h)).json()["user"]["id"]

    r = await client.post("/api/teams", json={"team_name": "Draft Gate Team"}, headers=innovator)
    team_id = r.json()["id"]
    r = await client.post(
        "/api/patents",
        json={"team_id": team_id, "invention_title": "Still Draft Widget"},
        headers=innovator,
    )
    pid = r.json()["id"]
    assert r.json()["application_status"] == "Draft"

    # Assigning a still-Draft patent IS allowed, by design.
    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_id}, headers=innovator
    )
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Awaiting Patent Agent Acceptance"

    # Once the agent accepts (Under Review), assign must now be rejected.
    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_h)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Under Review"

    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_id}, headers=innovator
    )
    assert r.status_code == 400, (
        f"Expected assigning an already-accepted (Under Review) patent to be rejected, "
        f"got {r.status_code}: {r.text}"
    )
