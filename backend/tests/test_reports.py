"""Regression tests for Phase 9 — Dashboard + Reports (app/api/reports.py,
app/services/reports_service.py).

Covers:
  - The personal dashboard's role-tailored "action required" figure and
    visibility-scoped status counts.
  - The two-tier report gate: the ordinary REPORTS_VIEW/REPORTS_DOWNLOAD
    RBAC permission codes (module "Reports", seeded in app/seed.py) gate
    the module generally, while the `report_permissions` table (present
    since the Phase 2 migration but unused until this session — see
    Project_Handover_v15.md §17's note about audit_logs being a similar
    "built but unused" case) gates CSV export per report type, and is
    itself only manageable by a Super Admin.
  - Admin/Super Admin bypass the fine-grained per-report-type gate (same
    posture as their bypass of team-membership checks elsewhere in the
    app) but still need the ordinary RBAC permission codes — which they
    have by default per app/seed.py.
  - Report content itself is scoped by the same `visible_patents_query`
    the patent list already uses, so a report never surfaces a patent an
    Innovator couldn't already see by listing their own patents.
"""

from tests.helpers import (
    assign_and_accept_agent,
    create_submitted_patent,
    grant_permission,
    grant_report_permission,
    revoke_permission,
    revoke_report_permission,
)


async def test_innovator_dashboard_action_required_is_draft_or_changes_requested(
    client, make_user
):
    innovator = await make_user("INNOVATOR", "innovator@dash-test.dev")

    r = await client.post(
        "/api/teams", json={"team_name": "Dash Team"}, headers=innovator
    )
    assert r.status_code in (200, 201), r.text
    team_id = r.json()["id"]

    r = await client.post(
        "/api/patents",
        json={"team_id": team_id, "invention_title": "Dash Widget"},
        headers=innovator,
    )
    assert r.status_code in (200, 201), r.text

    r = await client.get("/api/reports/dashboard", headers=innovator)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_visible_patents"] == 1
    assert body["status_counts"] == [{"status": "Draft", "count": 1}]
    assert body["action_required_count"] == 1
    assert "Draft or Changes Requested" in body["action_required_label"]
    assert body["recent_activity"] is None  # not an Admin/Super Admin


async def test_agent_dashboard_action_required_is_awaiting_acceptance(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@dash-agent-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@dash-agent-test.dev")
    pid, _ = await create_submitted_patent(client, innovator, "Agent Dash Widget")

    r = await client.get("/api/auth/me", headers=agent)
    agent_id = r.json()["user"]["id"]
    r = await client.post(
        f"/api/patents/{pid}/assign", json={"patent_agent_id": agent_id}, headers=innovator
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/reports/dashboard", headers=agent)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action_required_count"] == 1
    assert body["action_required_label"] == "Assignments awaiting your acceptance"
    assert body["status_counts"] == [
        {"status": "Awaiting Patent Agent Acceptance", "count": 1}
    ]


async def test_admin_dashboard_action_required_is_unassigned_submitted(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@dash-admin-test.dev")
    admin = await make_user("ADMIN", "admin@dash-admin-test.dev")
    await create_submitted_patent(client, innovator, "Admin Dash Widget")

    r = await client.get("/api/reports/dashboard", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action_required_count"] >= 1
    assert body["action_required_label"] == "Submitted applications awaiting agent assignment"
    # Admin/Super Admin get a recent_activity feed (may be empty, not None).
    assert body["recent_activity"] is not None


async def test_report_endpoints_require_reports_view_permission(client, make_user):
    """Regression guard: without REPORTS_VIEW, listing/viewing reports is
    rejected — dashboard remains available regardless (tested above)."""
    innovator = await make_user("INNOVATOR", "innovator@reports-authz-test.dev")

    r = await client.get("/api/reports", headers=innovator)
    assert r.status_code == 403

    r = await client.get("/api/reports/STATUS_BREAKDOWN", headers=innovator)
    assert r.status_code == 403

    r = await client.get("/api/reports/STATUS_BREAKDOWN/export", headers=innovator)
    assert r.status_code == 403


async def test_two_tier_download_gate_for_non_admin_role(client, make_user):
    """A role can be granted REPORTS_VIEW/REPORTS_DOWNLOAD (RBAC) without
    yet being able to download any specific report (ReportPermission) —
    both gates must pass, and the ReportPermission grant is per report
    type, not a blanket unlock."""
    super_admin = await make_user("SUPER_ADMIN", "superadmin@twotier-test.dev")
    innovator = await make_user("INNOVATOR", "innovator@twotier-test.dev")
    await create_submitted_patent(client, innovator, "Two Tier Widget")

    await grant_permission(client, super_admin, "INNOVATOR", "REPORTS_VIEW")
    try:
        r = await client.get("/api/reports", headers=innovator)
        assert r.status_code == 200, r.text
        types = {row["report_type"]: row["can_download"] for row in r.json()}
        assert types["STATUS_BREAKDOWN"] is False

        # RBAC permission granted but no REPORTS_DOWNLOAD yet -> still blocked.
        r = await client.get("/api/reports/STATUS_BREAKDOWN/export", headers=innovator)
        assert r.status_code == 403

        await grant_permission(client, super_admin, "INNOVATOR", "REPORTS_DOWNLOAD")
        try:
            # REPORTS_DOWNLOAD granted, but no per-report-type
            # ReportPermission row yet -> still blocked, with the
            # finer-grained error message.
            r = await client.get("/api/reports/STATUS_BREAKDOWN/export", headers=innovator)
            assert r.status_code == 403
            assert "isn't permitted to download" in r.json()["detail"]

            await grant_report_permission(client, super_admin, "INNOVATOR", "STATUS_BREAKDOWN")
            try:
                r = await client.get("/api/reports/STATUS_BREAKDOWN/export", headers=innovator)
                assert r.status_code == 200, r.text
                assert r.headers["content-type"].startswith("text/csv")
                assert "status,count" in r.text

                # The grant is scoped to STATUS_BREAKDOWN only — a
                # different report type must still be blocked.
                r = await client.get("/api/reports/TEAM_SUMMARY/export", headers=innovator)
                assert r.status_code == 403
            finally:
                await revoke_report_permission(
                    client, super_admin, "INNOVATOR", "STATUS_BREAKDOWN"
                )
        finally:
            await revoke_permission(client, super_admin, "INNOVATOR", "REPORTS_DOWNLOAD")
    finally:
        await revoke_permission(client, super_admin, "INNOVATOR", "REPORTS_VIEW")


async def test_admin_bypasses_reports_view_and_download_gates_entirely(client, make_user):
    """Plain Admin (not just Super Admin) needs no explicit RBAC grant and
    no ReportPermission row to view or download any report — see
    api/reports.py's module docstring for why Admin is bypassed at both
    layers while Innovator/Patent Agent are not."""
    innovator = await make_user("INNOVATOR", "innovator@bypass-test.dev")
    await create_submitted_patent(client, innovator, "Bypass Widget")

    admin = await make_user("ADMIN", "admin@bypass-test.dev")

    r = await client.get("/api/reports", headers=admin)
    assert r.status_code == 200, r.text
    assert all(row["can_download"] for row in r.json())

    r = await client.get("/api/reports/AGENT_WORKLOAD", headers=admin)
    assert r.status_code == 200, r.text

    r = await client.get("/api/reports/AGENT_WORKLOAD/export", headers=admin)
    assert r.status_code == 200, r.text


async def test_status_breakdown_and_agent_workload_content(client, make_user):
    innovator = await make_user("INNOVATOR", "innovator@content-test.dev")
    agent = await make_user("PATENT_AGENT", "agent@content-test.dev")
    super_admin = await make_user("SUPER_ADMIN", "superadmin@content-test.dev")

    pid, _ = await create_submitted_patent(client, innovator, "Content Widget")
    agent_id = await assign_and_accept_agent(client, innovator, agent, pid)

    r = await client.get("/api/reports/STATUS_BREAKDOWN", headers=super_admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_type"] == "STATUS_BREAKDOWN"
    assert {"status": "Under Review", "count": 1} in body["rows"]

    r = await client.get("/api/reports/AGENT_WORKLOAD", headers=super_admin)
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    row = next(row for row in rows if row["agent_id"] == agent_id)
    assert row["active_count"] == 1
    assert row["total_count"] == 1


async def test_innovator_report_scoped_to_own_visible_patents(client, make_user):
    """A report is just aggregation on top of visible_patents_query — an
    Innovator's report must not include another Innovator's patent."""
    super_admin = await make_user("SUPER_ADMIN", "superadmin@scope-test.dev")
    inno_a = await make_user("INNOVATOR", "innoA@scope-test.dev")
    inno_b = await make_user("INNOVATOR", "innoB@scope-test.dev")

    await grant_permission(client, super_admin, "INNOVATOR", "REPORTS_VIEW")
    try:
        await create_submitted_patent(client, inno_a, "Scope Widget A")
        r = await client.post(
            "/api/teams", json={"team_name": "Scope Team B"}, headers=inno_b
        )
        team_b = r.json()["id"]
        await client.post(
            "/api/patents",
            json={"team_id": team_b, "invention_title": "Scope Widget B"},
            headers=inno_b,
        )

        r = await client.get("/api/reports/STATUS_BREAKDOWN", headers=inno_b)
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        # inno_b only sees their own Draft patent, not inno_a's Submitted one.
        assert rows == [{"status": "Draft", "count": 1}]
    finally:
        await revoke_permission(client, super_admin, "INNOVATOR", "REPORTS_VIEW")


async def test_only_super_admin_manages_report_permission_matrix(client, make_user):
    admin = await make_user("ADMIN", "admin@matrix-authz-test.dev")
    super_admin = await make_user("SUPER_ADMIN", "superadmin@matrix-authz-test.dev")

    r = await client.get("/api/reports/permissions/matrix", headers=admin)
    assert r.status_code == 403

    r = await client.post(
        "/api/reports/permissions/toggle?grant=true",
        json={"role_id": 1, "report_type": "STATUS_BREAKDOWN"},
        headers=admin,
    )
    assert r.status_code == 403

    r = await client.get("/api/reports/permissions/matrix", headers=super_admin)
    assert r.status_code == 200, r.text
    assert "STATUS_BREAKDOWN" in {rt["report_type"] for rt in r.json()["report_types"]}


async def test_toggle_unknown_report_type_rejected(client, make_user):
    super_admin = await make_user("SUPER_ADMIN", "superadmin@unknown-report-test.dev")
    r = await client.post(
        "/api/reports/permissions/toggle?grant=true",
        json={"role_id": 1, "report_type": "NOT_A_REAL_REPORT"},
        headers=super_admin,
    )
    assert r.status_code == 400
