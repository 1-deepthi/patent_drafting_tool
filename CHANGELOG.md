# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once releases begin.

## [Unreleased]

### Added

- Full open-source documentation set: detailed `README.md`, `CONTRIBUTING.md`, Contributor Covenant `CODE_OF_CONDUCT.md`, `SECURITY.md`, `ACCESSIBILITY.md` (WCAG 2.2 AA target), `SUPPORT.md`, and `docs/` guides (`GETTING_STARTED`, `ARCHITECTURE`, `API_OVERVIEW`, `DEVELOPMENT`, `DOCKER`, `FAQ`, `TROUBLESHOOTING`).
- GitHub community health files: PR template, bug/feature/docs issue forms, `config.yml`, `CODEOWNERS`, `dependabot.yml`, Discussions-ready links.
- CI/CD: `ci.yml` (offline backend pytest, frontend build on `ubuntu`/`windows`/`macos`, docs-health), `docker.yml` (backend + frontend image builds + backend `/health` smoke test), `codeql.yml` (CodeQL for Python + JavaScript).
- Apache-2.0 `LICENSE` with `SPDX-License-Identifier` notice.
- Root `.editorconfig`, `.nvmrc` (Node 20), `backend/.python-version` (3.13), hardened root `.gitignore`.
- Architecture Decision Records in `docs/decisions/`: ADR-001 Firebase runtime (superseded), ADR-002 `role_codes` array, ADR-003 single instance, ADR-004 stub-first AI, ADR-005 Firestore-only runtime.
- `AGENTS.md` (agent instructions), `CITATION.cff`, `docs/FAQ.md`, `docs/TROUBLESHOOTING.md`; `ref-repos/` convention for ignored reference clones.
- Shared centred `LoadingState` / `EmptyState` frontend components replacing scattered left-aligned loading/empty paragraphs; wrapping dashboard header for small screens.
- Browser-side Firebase Authentication in the React client (`src/lib/firebase.ts`, `AuthContext`), with Google popup and redirect fallback, a configuration-error banner, and a 30-minute idle sign-out.
- Offline backend test suite (`backend/tests/`) covering boot, the mounted frontend contract, RBAC, stub drafting, and DOCX rendering — no Firebase credentials required.
- Runtime capability probe (`GET /api/config/capabilities`) and configurable deployment limits: `DEPLOYMENT_TARGET`, `MAX_UPLOAD_SIZE_BYTES`, and `PDF_CONVERSION_ENABLED`. The frontend pre-checks upload sizes and hides PDF generation when the deployment cannot run LibreOffice.

### Changed

- **Firebase is the only backend.** Postgres, SQLAlchemy, Alembic, asyncpg/psycopg, the legacy routers/models/schemas/services, `docker-entrypoint.sh`, the SQL test suite, and the advisory CI job are all removed (ADR-005).
- All application data now lives in Cloud Firestore; uploaded files, templates, and generated documents live in Cloud Storage. Database and storage-provider environment variables are gone.
- The REST API keeps the existing snake_case contract (`invention_title`, `application_status`, `roles`, Title-Case statuses) through `app/services/projections.py`; Firestore stores lowercase `account_status` / `role_codes`.
- Entity identifiers are Firestore strings end to end; `Number(id)` casts were removed from the frontend. Only RBAC role/permission catalog IDs remain numeric.
- `frontend/src/lib/api.ts` now registers an async token provider (`setTokenProvider`) and asks Firebase for a fresh ID token per request, replacing the cached-token `setAuthToken` approach.
- DOCX generation uses `docxtpl` when an active template exists and a built-in `python-docx` layout otherwise; PDF conversion shells out to headless LibreOffice.
- `docker-compose.yml` runs the backend + frontend images only; `backend/Dockerfile` drops the entrypoint and runs two Gunicorn/Uvicorn workers; `frontend/Dockerfile` accepts the six `VITE_FIREBASE_*` build args.
- CI runs the offline Firebase suite on Python 3.11/3.13 across three operating systems, and `docs-health` rejects stale SQL references in shipped code.
- `README.md`, `DEPLOYMENT.md`, `backend/README.md`, and every `docs/` guide rewritten for the Firebase-only runtime and offline workflow.
- `DEPLOYMENT.md` rewritten for a Firebase project + one backend container + static/nginx frontend, with no managed Postgres or object-store vendor.

### Removed

- Server-minted JWTs, the refresh endpoint, the backend Google OAuth redirect, dev login, and the legacy auth modules.
- In-memory rate limiting and the SQL-era startup checks (the Firebase runtime relies on platform-level limits; see ADR-003).
- `DATABASE_URL`, `JWT_SECRET`, `SESSION_SECRET`, `GOOGLE_CLIENT_ID`/`SECRET`, `STORAGE_PROVIDER`, and the `R2_*` variables from documentation and configuration.

### Fixed

- Docker workflow used the non-existent `docker/build-action` (failed at "Set up job") — corrected to `docker/build-push-action`; action existence is verified before merging workflow changes.
- Frontend no longer crashes at import time when Firebase Web SDK values are missing; it renders a configuration error on the login screen instead.

### Known gaps (tracked, not yet fixed)

- Frontend has no unit-test runner yet; verification is `tsc` + `vite build` + manual role walkthroughs.
- The offline suite cannot prove live Firebase IAM, Firestore rules, Storage rules, or LibreOffice PDF conversion; a manual walkthrough against a real Firebase project remains the release check (`backend/README.md` §7).
- Application statuses beyond `Draft Generated` (filing, examination, grant) are accepted and displayed but have no transition endpoint yet.

## [0.1.0] - 2026-10-15 (pre-revolution baseline)

Baseline inherited from prior development (see git history):

- `58362d3 Implement patent workflow, reports, testing, and deployment`
- `8232dfb Integrate Firebase backend`

Included: role-based dashboards (Innovator / Agent / Admin / Super Admin), patent assignment state machine, questionnaire + versions, stub/Gemini draft generation, DOCX generation, file uploads, comments, calendar, notifications, templates, reports, Docker images, and Compose for local full-stack testing.
