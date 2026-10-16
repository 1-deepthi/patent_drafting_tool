# FAQ

Short answers to questions that come up repeatedly. Longer guides: [`GETTING_STARTED.md`](./GETTING_STARTED.md), [`ARCHITECTURE.md`](./ARCHITECTURE.md), [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md).

## Product

**Is generated patent text legal advice?**
No. Every draft — stub or Gemini — is a drafting aid with an explicit not-legal-advice warning. A qualified patent professional must review anything before filing.

**Who is this for?**
Innovators (disclose inventions), patent agents (review and draft), admins (approve users, assign agents, manage templates), and super admins (roles, permissions, reports). See README §3.

**Which backend is live — Firebase or Postgres?**
Firebase (Authentication, Firestore, Storage). The Postgres/SQLAlchemy code in-tree is an unmounted reference implementation kept until the migration is validated. See [ADR-001](./decisions/ADR-001-firebase-active-runtime.md).

## Setup

**Do I need Firebase to run this?**
Yes for anything beyond the login screen. Without credentials the backend boots but `/health` returns `503 degraded` and authenticated calls fail. The Firebase Console steps are in [`GETTING_STARTED.md`](./GETTING_STARTED.md#3-create-the-firebase-project).

**Why do I get `403 awaiting approval`?**
New accounts are `pending` until an Admin approves them. The `BOOTSTRAP_ADMIN_EMAIL` address becomes Super Admin on first sign-in and can then approve others.

**Dev login returns 404 — is it broken?**
Dev login is a legacy SQL affordance, not part of the active Firebase path. Use Firebase Authentication. See [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md).

**Port 8000 (or 5432) is already in use on my machine.**
Run the backend on another port (e.g. `8001`) and point `VITE_API_URL` at it, or remap Compose ports. See [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md#ports-already-in-use).

## Contributing

**Where do I start?**
`CONTRIBUTING.md` (root) + `AGENTS.md` (root, agent-oriented). Pick a `good first issue`, follow the commit-discipline rules (atomic commits, one type per commit), and fill the PR template.

**Why did CI run the legacy test suite as "allowed to fail"?**
`backend/tests/` still target the archived SQL API. The `backend-legacy-suite` job tracks that migration debt without blocking merges. See [`ARCHITECTURE.md`](./ARCHITECTURE.md#8-legacy-postgres-path-reference-only).

**How should I cite this project?**
See `CITATION.cff` at the repo root (GitHub renders a *Cite this repository* button from it).

**What license is this?**
Apache-2.0 — see `LICENSE`. Contributions are accepted under the same license.
