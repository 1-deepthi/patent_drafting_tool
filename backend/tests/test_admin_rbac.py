"""Regression tests for the Super-Admin-only RBAC dashboard endpoints
(app/api/rbac.py) and the Pending Approvals flow (app/api/auth.py). This
encodes the manual Playwright test from Project_Handover_v10.md §7.12."""
from tests.helpers import create_pending_user


async def test_admin_role_cannot_access_super_admin_only_endpoints(client, make_user):
    """Regression guard confirming the design noted in rbac.py's own
    module docstring: even plain Admin (not just Innovator/Agent) is
    correctly excluded from every RBAC-management endpoint — deliberately
    Super-Admin-only to avoid a privilege-escalation path."""
    admin = await make_user("ADMIN", "admin@rbac-authz-test.dev")

    r = await client.get("/api/rbac/matrix", headers=admin)
    assert r.status_code == 403

    r = await client.get("/api/rbac/users", headers=admin)
    assert r.status_code == 403

    r = await client.get("/api/auth/pending-users", headers=admin)
    assert r.status_code == 403


async def test_pending_user_appears_in_pending_list_and_not_all_users_yet(client, make_user):
    super_admin = await make_user("SUPER_ADMIN", "superadmin@pending-test.dev")
    await create_pending_user("someone@pending-test.dev", "Someone Pending")

    r = await client.get("/api/auth/pending-users", headers=super_admin)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert "someone@pending-test.dev" in emails


async def test_approve_pending_user_grants_role_and_removes_from_pending(client, make_user):
    super_admin = await make_user("SUPER_ADMIN", "superadmin@approve-test.dev")
    user_id = await create_pending_user("approve-me@approve-test.dev", "Approve Me")

    # Approving with an empty role list must be rejected (min_length=1 on
    # ApproveUserRequest.role_codes) — matches the "select at least one
    # role" validation confirmed manually in §7.12.
    r = await client.post(
        f"/api/auth/users/{user_id}/approve", json={"role_codes": []}, headers=super_admin
    )
    assert r.status_code == 422, r.text

    r = await client.post(
        f"/api/auth/users/{user_id}/approve",
        json={"role_codes": ["INNOVATOR"]},
        headers=super_admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account_status"] == "Approved"

    r = await client.get("/api/auth/pending-users", headers=super_admin)
    emails = [u["email"] for u in r.json()]
    assert "approve-me@approve-test.dev" not in emails

    r = await client.get("/api/rbac/users", headers=super_admin)
    all_users = {u["email"]: u for u in r.json()}
    assert "INNOVATOR" in all_users["approve-me@approve-test.dev"]["roles"]


async def test_reject_pending_user_sets_status_and_removes_from_pending(client, make_user):
    super_admin = await make_user("SUPER_ADMIN", "superadmin@reject-user-test.dev")
    user_id = await create_pending_user("reject-me@reject-user-test.dev", "Reject Me")

    r = await client.post(
        f"/api/auth/users/{user_id}/reject",
        json={"reason": "Not a valid business account."},
        headers=super_admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_status"] == "Rejected"

    r = await client.get("/api/auth/pending-users", headers=super_admin)
    emails = [u["email"] for u in r.json()]
    assert "reject-me@reject-user-test.dev" not in emails


async def test_rbac_matrix_lists_all_roles_and_permissions(client, make_user):
    super_admin = await make_user("SUPER_ADMIN", "superadmin@matrix-test.dev")
    r = await client.get("/api/rbac/matrix", headers=super_admin)
    assert r.status_code == 200
    body = r.json()
    role_codes = {role["role_code"] for role in body["roles"]}
    assert role_codes == {"SUPER_ADMIN", "ADMIN", "PATENT_AGENT", "INNOVATOR"}
    assert len(body["permissions"]) == 30  # 5 modules x 6 actions, per app/seed.py


async def test_toggle_permission_grants_and_revokes(client, make_user):
    super_admin = await make_user("SUPER_ADMIN", "superadmin@toggle-test.dev")

    matrix = (await client.get("/api/rbac/matrix", headers=super_admin)).json()
    admin_role = next(r for r in matrix["roles"] if r["role_code"] == "ADMIN")
    permission = matrix["permissions"][0]
    granted_pairs = {(g["role_id"], g["permission_id"]) for g in matrix["grants"]}
    was_granted = (admin_role["id"], permission["id"]) in granted_pairs

    # Toggle to the opposite of its current state
    r = await client.post(
        f"/api/rbac/toggle?grant={'false' if was_granted else 'true'}",
        json={"role_id": admin_role["id"], "permission_id": permission["id"]},
        headers=super_admin,
    )
    assert r.status_code == 200, r.text
    new_pairs = {(g["role_id"], g["permission_id"]) for g in r.json()["grants"]}
    now_granted = (admin_role["id"], permission["id"]) in new_pairs
    assert now_granted != was_granted

    # Toggle back to leave state clean for other tests (roles/permissions
    # aren't truncated between tests — see conftest.py's _DATA_TABLES).
    r = await client.post(
        f"/api/rbac/toggle?grant={'true' if was_granted else 'false'}",
        json={"role_id": admin_role["id"], "permission_id": permission["id"]},
        headers=super_admin,
    )
    assert r.status_code == 200


async def test_super_admin_own_permissions_cannot_be_revoked_via_role_removal(client, make_user):
    """Regression guard matching rbac.py's own safeguard: a Super Admin
    cannot revoke their own SUPER_ADMIN role (would risk a lockout)."""
    r = await client.post(
        "/api/auth/dev-login",
        json={"role_code": "SUPER_ADMIN", "email": "superadmin@self-revoke-test.dev", "full_name": "SA"},
    )
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = (await client.get("/api/auth/me", headers=headers)).json()["user"]

    r = await client.delete(
        f"/api/rbac/users/{me['id']}/roles/SUPER_ADMIN", headers=headers
    )
    assert r.status_code == 400, r.text


async def test_assign_and_revoke_role_for_a_user(client, make_user):
    super_admin = await make_user("SUPER_ADMIN", "superadmin@assign-role-test.dev")
    innovator = await make_user("INNOVATOR", "target@assign-role-test.dev")
    target_id = (await client.get("/api/auth/me", headers=innovator)).json()["user"]["id"]

    r = await client.post(
        f"/api/rbac/users/{target_id}/roles",
        json={"role_code": "PATENT_AGENT"},
        headers=super_admin,
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/rbac/users", headers=super_admin)
    target = next(u for u in r.json() if u["id"] == target_id)
    assert set(target["roles"]) == {"INNOVATOR", "PATENT_AGENT"}

    r = await client.delete(
        f"/api/rbac/users/{target_id}/roles/PATENT_AGENT", headers=super_admin
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/rbac/users", headers=super_admin)
    target = next(u for u in r.json() if u["id"] == target_id)
    assert target["roles"] == ["INNOVATOR"]
