"""Regression tests for the finding in Project_Handover_v14.md §12.3:

Assigning an agent while a patent is still in "Draft" is intentional,
tested design (see test_can_assign_agent_even_before_submission_but_not_after_acceptance
in test_assignment_workflow.py). Assignment jumps the application straight
to "Awaiting Patent Agent Acceptance" without ever requiring — or even
allowing — the Basic Information / questionnaire steps to be completed
first. Before the fix, both of those steps gated strictly on
application_status == "Draft", so once assigned early, they became
permanently uneditable (nothing ever moves the status back to "Draft").

The fix widens that gate to PRE_ASSIGNMENT_STATUSES (Draft, Submitted,
Awaiting Patent Agent Acceptance) — i.e. editable any time before the
agent has actually accepted. These tests lock that behavior in and also
confirm the gate still closes once the agent accepts (Under Review).
"""


async def _create_draft_patent(client, innovator_headers, title):
    r = await client.post(
        "/api/teams", json={"team_name": f"Team for {title}"}, headers=innovator_headers
    )
    assert r.status_code in (200, 201), r.text
    team_id = r.json()["id"]

    r = await client.post(
        "/api/patents",
        json={"team_id": team_id, "invention_title": title},
        headers=innovator_headers,
    )
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    assert r.json()["application_status"] == "Draft"
    return pid, team_id


_QUESTIONNAIRE_PAYLOAD = {
    "invention_type": "Software",
    "problem_statement": "Existing systems are slow.",
    "proposed_solution": "A faster system using caching.",
    "novelty_description": "Novel caching layer.",
    "technical_description": "Uses a distributed cache with TTL eviction.",
    "advantages": "Faster response times.",
    "prior_art": "None found.",
    "keywords": "caching, performance",
    "has_existing_drawings": False,
}


async def test_questionnaire_editable_after_early_assignment_but_not_after_acceptance(
    client, make_user
):
    innovator = await make_user("INNOVATOR", "innovator@early-assign-q.dev")
    agent_h = await make_user("PATENT_AGENT", "agent@early-assign-q.dev")
    agent_id = (await client.get("/api/auth/me", headers=agent_h)).json()["user"]["id"]

    pid, _ = await _create_draft_patent(client, innovator, "Early Assign Widget")

    # Assign while still Draft — intentional design, jumps straight to
    # "Awaiting Patent Agent Acceptance" without ever passing through the
    # normal /submit completeness gate.
    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_id}, headers=innovator
    )
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Awaiting Patent Agent Acceptance"

    # Before the fix this 400'd forever: the questionnaire must still be
    # fillable so the applicant can actually finish it.
    r = await client.patch(
        f"/api/patents/{pid}/questionnaire", json=_QUESTIONNAIRE_PAYLOAD, headers=innovator
    )
    assert r.status_code == 200, r.text

    r = await client.post(f"/api/patents/{pid}/questionnaire/submit", headers=innovator)
    assert r.status_code == 200, r.text
    assert r.json()["questionnaire_status"] == "Completed"

    # Once the agent accepts, the questionnaire locks — same as it always
    # has post-acceptance.
    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_h)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Under Review"

    r = await client.patch(
        f"/api/patents/{pid}/questionnaire", json=_QUESTIONNAIRE_PAYLOAD, headers=innovator
    )
    assert r.status_code == 400, r.text


async def test_basic_info_editable_after_early_assignment_but_not_after_acceptance(
    client, make_user
):
    innovator = await make_user("INNOVATOR", "innovator@early-assign-bi.dev")
    agent_h = await make_user("PATENT_AGENT", "agent@early-assign-bi.dev")
    agent_id = (await client.get("/api/auth/me", headers=agent_h)).json()["user"]["id"]

    pid, _ = await _create_draft_patent(client, innovator, "Early Assign BI Widget")

    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_id}, headers=innovator
    )
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Awaiting Patent Agent Acceptance"

    # Before the fix, these 400'd forever too — the innovator would never
    # be able to fill in Applicants/Inventors for an application assigned
    # this early.
    r = await client.post(
        f"/api/patents/{pid}/applicants",
        json={
            "applicant_type": "Individual",
            "full_name_or_org_name": "Jane Doe",
            "country": "IN",
            "is_primary": True,
        },
        headers=innovator,
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/patents/{pid}/inventors",
        json={"full_name": "Jane Doe", "country": "IN"},
        headers=innovator,
    )
    assert r.status_code == 201, r.text

    r = await client.post(f"/api/patents/{pid}/assignment/accept", headers=agent_h)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Under Review"

    r = await client.post(
        f"/api/patents/{pid}/inventors",
        json={"full_name": "Post-Accept Inventor", "country": "IN"},
        headers=innovator,
    )
    assert r.status_code == 400, r.text


async def test_questionnaire_still_editable_while_submitted_but_not_yet_assigned(
    client, make_user
):
    """Same fix, a narrower slice: previously even a Submitted-but-not-yet-
    assigned application couldn't have its questionnaire touched again
    (e.g. to fix a typo) since Submitted != Draft either. That's now
    allowed too, since Submitted is also a PRE_ASSIGNMENT_STATUSES status.
    """
    innovator = await make_user("INNOVATOR", "innovator@submitted-edit.dev")
    pid, _ = await _create_draft_patent(client, innovator, "Submitted Edit Widget")

    r = await client.post(
        f"/api/patents/{pid}/applicants",
        json={
            "applicant_type": "Individual",
            "full_name_or_org_name": "Jane Doe",
            "country": "IN",
            "is_primary": True,
        },
        headers=innovator,
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/patents/{pid}/inventors",
        json={"full_name": "Jane Doe", "country": "IN"},
        headers=innovator,
    )
    assert r.status_code == 201, r.text

    r = await client.patch(
        f"/api/patents/{pid}/questionnaire", json=_QUESTIONNAIRE_PAYLOAD, headers=innovator
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/patents/{pid}/questionnaire/submit", headers=innovator)
    assert r.status_code == 200, r.text

    r = await client.post(f"/api/patents/{pid}/submit", headers=innovator)
    assert r.status_code == 200, r.text
    assert r.json()["application_status"] == "Submitted"

    fixed_payload = dict(_QUESTIONNAIRE_PAYLOAD, problem_statement="Fixed typo in problem statement.")
    r = await client.patch(
        f"/api/patents/{pid}/questionnaire", json=fixed_payload, headers=innovator
    )
    assert r.status_code == 200, r.text
    assert r.json()["problem_statement"] == "Fixed typo in problem statement."
