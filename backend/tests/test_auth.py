"""Auth / dev-login tests. Also serves to validate the test fixture
infrastructure itself (client, make_user, DB truncation) before the
larger workflow suites build on top of it."""


async def test_dev_login_issues_token_for_each_seeded_role(client, make_user):
    for role_code in ("INNOVATOR", "PATENT_AGENT", "ADMIN", "SUPER_ADMIN"):
        headers = await make_user(role_code, f"{role_code.lower()}@fixture-test.dev")
        assert headers["Authorization"].startswith("Bearer ")


async def test_dev_login_unknown_role_code_rejected(client):
    resp = await client.post(
        "/api/auth/dev-login",
        json={"role_code": "NOT_A_REAL_ROLE", "email": "x@test.dev", "full_name": "X"},
    )
    assert resp.status_code in (400, 404, 422)


async def test_dev_login_is_idempotent_per_email(client, make_user):
    """Regression guard for the test-data hygiene gotcha in
    Project_Handover_v10.md §7.12: calling dev-login twice with the same
    email must return the SAME underlying user, not create a duplicate."""
    h1 = await make_user("INNOVATOR", "repeat@fixture-test.dev", "First Name")
    h2 = await make_user("INNOVATOR", "repeat@fixture-test.dev", "Second Name")

    me1 = await client.get("/api/auth/me", headers=h1)
    me2 = await client.get("/api/auth/me", headers=h2)
    assert me1.status_code == 200 and me2.status_code == 200
    assert me1.json()["user"]["id"] == me2.json()["user"]["id"]


async def test_unauthenticated_request_is_rejected(client):
    resp = await client.get("/api/patents/1")
    assert resp.status_code in (401, 403)


async def test_innovator_cannot_access_admin_only_rbac_matrix(client, make_user):
    headers = await make_user("INNOVATOR", "plain_innovator@fixture-test.dev")
    resp = await client.get("/api/rbac/matrix", headers=headers)
    assert resp.status_code == 403
