<div align="center">
  <h1>patent_drafting_tool</h1>
  <p><em>An open-source collaborative platform for drafting, reviewing, and managing patent applications — from invention disclosure to filing-ready documents.</em></p>
  <p>
    <a href="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/ci.yml"><img src="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
    <a href="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/docker.yml"><img src="https://github.com/auraflaa/patent_drafting_tool/actions/workflows/docker.yml/badge.svg" alt="Docker status"></a>
    <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
    <a href="./CODE_OF_CONDUCT.md"><img src="https://img.shields.io/badge/Code%20of%20Conduct-Contributor%20Covenant-4baaaa.svg" alt="Code of Conduct"></a>
    <a href="./CONTRIBUTING.md"><img src="https://img.shields.io/badge/Contributing-Guide-green.svg" alt="Contributing guide"></a>
    <a href="./SECURITY.md"><img src="https://img.shields.io/badge/Security-Policy-red.svg" alt="Security policy"></a>
    <a href="./ACCESSIBILITY.md"><img src="https://img.shields.io/badge/Accessibility-WCAG%202.2%20AA-purple.svg" alt="Accessibility: WCAG 2.2 AA"></a>
    <a href="./CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome"></a>
  </p>
</div>

---

## Table of contents

- [1. What this is](#1-what-this-is)
- [2. Features](#2-features)
- [3. Who it is for (roles)](#3-who-it-is-for-roles)
- [4. Patent lifecycle](#4-patent-lifecycle)
- [5. Tech stack](#5-tech-stack)
- [6. Repository layout](#6-repository-layout)
- [7. Quickstart](#7-quickstart)
  - [7.1 Prerequisites](#71-prerequisites)
  - [7.2 Option A — Docker Compose (recommended for first run)](#72-option-a--docker-compose-recommended-for-first-run)
  - [7.3 Option B — Run backend + frontend locally](#73-option-b--run-backend--frontend-locally)
  - [7.4 First admin login](#74-first-admin-login)
- [8. Configuration (environment variables)](#8-configuration-environment-variables)
  - [8.1 Backend (`backend/.env`)](#81-backend-backenvenv)
  - [8.2 Frontend (`frontend/.env`)](#82-frontend-frontendenv)
- [9. Usage walkthrough](#9-usage-walkthrough)
- [10. API overview](#10-api-overview)
- [11. Development](#11-development)
- [12. Testing](#12-testing)
- [13. Docker](#13-docker)
- [14. Deployment](#14-deployment)
- [15. Documentation index](#15-documentation-index)
- [16. Contributing](#16-contributing)
- [17. Code of Conduct](#17-code-of-conduct)
- [18. Security](#18-security)
- [19. Accessibility](#19-accessibility)
- [20. Support](#20-support)
- [21. Changelog](#21-changelog)
- [22. License](#22-license)
- [23. Acknowledgements](#23-acknowledgements)

---

## 1. What this is

**patent_drafting_tool** is a full-stack web application that helps teams prepare patent applications:

- **Innovators** disclose inventions via structured questionnaires, track status, and collaborate with agents.
- **Patent agents** review disclosures, accept assignments, generate draft sections (with optional AI assistance), and produce DOCX documents.
- **Admins / Super Admins** manage users, approve accounts, assign agents, manage templates, and view reports.

The project is currently in an **active migration**:

- **Current runtime (documented in [`backend/README.md`](./backend/README.md)):** Firebase-native backend — Firebase Authentication (ID tokens), Cloud Firestore (application data), Cloud Storage (file uploads).
- **Legacy code still present in the tree:** a Postgres + SQLAlchemy + Alembic backend (`backend/app/models/`, `backend/alembic/`, parts of `backend/app/services/` and `backend/tests/`). It is **not mounted** by `backend/app/main.py` (which only mounts `auth` + `resources` routers) and is **not** the deployment target. It is kept for reference until the migration is validated.
- **Deployment target:** single-container PaaS (Koyeb) + Neon Postgres historically; Firebase project + static/container frontend going forward. See [`DEPLOYMENT.md`](./DEPLOYMENT.md) and [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md).

> Generated patent text is a **draft only** and is **not legal advice**. Final review by a qualified patent professional is required before filing.

---

## 2. Features

| Area | What you get |
|---|---|
| Invention intake | Teams, patent records, applicant/inventor parties, structured questionnaire with versions |
| Agent workflow | Available-agent listing, assign / auto-assign / reassign, accept / reject with reasons |
| Drafting | Section-wise draft generation (`summary`, `background`, `description`, `claims`, `abstract`), version history; stub provider by default, optional Gemini provider |
| Documents | DOCX generation from basic info + questionnaire answers, version list, signed-URL download, retry |
| Files | Patent-scoped uploads to Firebase Storage, size/extension validation, signed-URL download, uploader/admin delete |
| Collaboration | Comments, calendar events, notifications (unread count, mark read) |
| Templates | Admin-managed `.docx` templates per document type, activate/deactivate, placeholder warnings |
| Reports & dashboard | Patent counts by status, patent/assignment catalogs, JSON export, permission-gated browser |
| Auth & RBAC | Firebase ID-token auth, `role_codes` (`INNOVATOR`, `PATENT_AGENT`, `ADMIN`, `SUPER_ADMIN`), pending → approved onboarding, bootstrap super-admin |
| Frontend | Role-based dashboards, patent workflow tabs, draft workspace, calendar (FullCalendar), reports (recharts), PDF preview (react-pdf) |
| Ops | `/health` with Firebase probe, CORS + TrustedHost, Docker images for backend + frontend, Compose for local full-stack |

---

## 3. Who it is for (roles)

| Role | Home route | Can do |
|---|---|---|
| `INNOVATOR` | `/innovator` | Create teams + patents, fill questionnaire, upload files, comment, submit for review, view own calendar/reports |
| `PATENT_AGENT` | `/agent` | View assignment queue, accept/decline, generate drafts, generate documents, collaborate |
| `ADMIN` | `/admin` | Approve users, assign/reassign agents, manage templates, view all patents, reports |
| `SUPER_ADMIN` | `/super-admin` | Everything admins can do, plus RBAC user/role management, report-permission matrix |

New users land in `pending` until an `ADMIN`/`SUPER_ADMIN` approves them. The single exception is the `BOOTSTRAP_ADMIN_EMAIL` address, which becomes `SUPER_ADMIN` on first sign-in. See [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md#first-admin-login).

---

## 4. Patent lifecycle

The full status vocabulary (legacy SQL model, `backend/app/models/patent.py`) is:

```text
Draft → Submitted → Awaiting Patent Agent Acceptance → Under Review
→ Changes Requested → Ready for Draft Generation → Draft Generated
→ Ready for Filing → Filed → Examination Requested → FER Received
→ FER Response Submitted → Hearing Scheduled → Granted / Rejected / Withdrawn / Abandoned
```

The active Firebase backend uses a simplified `status` / `workflow_status` pair (`draft`, `submitted`, `under_review`, plus assignment states `pending`, `accepted`, `rejected`). The Firestore state machine is enforced in `backend/app/api/resources.py` (owner/admin guards, agent-accept guards). See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md#patent-state-machine).

---

## 5. Tech stack

**Backend (`backend/`)**

| Layer | Technology |
|---|---|
| API | FastAPI `>=0.115,<1.0`, Uvicorn, Pydantic Settings |
| Auth / data / storage (active) | `firebase-admin >=6.6,<8.0`, Cloud Firestore, Cloud Storage, Firebase Authentication |
| Docs generation | `python-docx`, LibreOffice (in Docker image for DOCX→PDF) |
| HTTP / uploads | `httpx`, `python-multipart` |
| Tests | `pytest >=8.3` |
| Runtime | Python 3.11+ (Docker: `python:3.13-slim`), Gunicorn + Uvicorn workers in production |

**Frontend (`frontend/`)**

| Layer | Technology |
|---|---|
| UI | React 18.3, React Router 6.28, Tailwind CSS 3.4 |
| Data / forms | TanStack React Query 5.62, React Hook Form 7.54, Zod 3.24 |
| Domain widgets | Recharts 2.15 (reports), FullCalendar 6.1 (calendar), react-pdf 9.2 (preview) |
| Build | Vite 6.0, TypeScript 5.7 (`strict`, `noUnusedLocals/Parameters`) |
| Runtime | Node 20 (Docker build stage), nginx 1.27-alpine (serve stage) |

**Infrastructure**

- `docker-compose.yml`: local Postgres + backend (gunicorn) for full-stack testing.
- `backend/Dockerfile`: multi-stage Python build, LibreOffice, non-root `appuser`, `HEALTHCHECK /health`, entrypoint migrates only on the legacy SQL path, then Gunicorn.
- `frontend/Dockerfile`: Node build → nginx serve with SPA fallback (`frontend/nginx.conf`).
- CI: `.github/workflows/ci.yml` (lint + test + build, cross-OS matrix) and `docker.yml` (image builds).

---

## 6. Repository layout

```text
patent_drafting_tool/
├── README.md                  # You are here
├── LICENSE                    # Apache-2.0
├── CODE_OF_CONDUCT.md         # Contributor Covenant 2.1
├── CONTRIBUTING.md            # How to set up, branch, test, and open PRs
├── SECURITY.md                # How to report vulnerabilities + hardening notes
├── ACCESSIBILITY.md           # WCAG 2.2 AA commitments + known gaps
├── SUPPORT.md                 # Where to get help
├── CHANGELOG.md               # Release history (Keep a Changelog)
├── DEPLOYMENT.md              # PaaS deployment guide (Koyeb/Neon/R2 + Firebase notes)
├── docker-compose.yml         # Local full-stack (postgres + backend)
├── docs/
│   ├── GETTING_STARTED.md     # Step-by-step first run
│   ├── ARCHITECTURE.md        # System, auth, data, and workflow design
│   ├── API_OVERVIEW.md        # Endpoint catalog
│   ├── DEVELOPMENT.md         # Conventions, scripts, troubleshooting
│   └── DOCKER.md              # Image, compose, and env reference
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── config.yml
│   │   ├── bug_report.yml
│   │   ├── feature_request.yml
│   │   └── documentation.yml
│   └── workflows/
│       ├── ci.yml             # Lint + test + build (ubuntu/windows/macos)
│       ├── docker.yml         # Docker build + smoke test
│       └── codeql.yml         # CodeQL security scanning
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, lifespan, /health, router mounts
│   │   ├── api/               # auth.py + resources.py (active); 13 legacy routers
│   │   ├── core/              # config, firebase, security, middleware, rate_limit
│   │   ├── models/            # Legacy SQLAlchemy models (reference)
│   │   ├── schemas/           # Pydantic schemas
│   │   └── services/          # repository (active Firestore CRUD) + legacy services + ai/
│   ├── tests/                 # pytest suite (legacy SQL targets; see §12)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── .env.example
│   └── README.md              # Firebase setup guide
└── frontend/
    ├── src/
    │   ├── App.tsx            # Route map + role guards
    │   ├── context/AuthContext.tsx
    │   ├── lib/api.ts         # apiFetch/apiUpload/apiDownload
    │   ├── lib/types.ts       # DTOs, status colors, role homes
    │   ├── components/        # Shell, ProtectedRoute, panels, bell, badges
    │   └── pages/             # 14 role-scoped pages
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    └── .env.example
```

---

## 7. Quickstart

### 7.1 Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ (3.13 recommended, see `backend/Dockerfile`) | `python --version` |
| Node | 20.x (see `frontend/Dockerfile` build stage) | `node --version` |
| npm | 10+ | Ships with Node 20 |
| Docker + Compose | 24+ / v2 | Only for Option A |
| Firebase project | Firestore + Authentication enabled | See `backend/README.md` §2 |

### 7.2 Option A — Docker Compose (recommended for first run)

```powershell
# From the repo root:
docker compose up --build
```

- Backend: http://localhost:8000 (`GET /health`, docs at `/docs`)
- Postgres: `localhost:5432` (`postgres/postgres/patent_platform`)
- Frontend is **not** in this Compose file — run it separately (Option B) or build its image (`docs/DOCKER.md`).

> Compose currently wires `DATABASE_URL` to the in-network `postgres` host for the legacy SQL path. The Firebase backend ignores it and uses `FIREBASE_*` env instead. `REDIS` is intentionally not included yet (see `docker-compose.yml` comment).

### 7.3 Option B — Run backend + frontend locally

**Backend (Windows PowerShell):**

```powershell
cd backend
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env — at minimum FIREBASE_PROJECT_ID, FIREBASE_STORAGE_BUCKET, BOOTSTRAP_ADMIN_EMAIL
python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs and http://127.0.0.1:8000/health.
`/health` returns `503` until Firebase credentials are valid — that is expected before setup.

**Frontend (new terminal):**

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
# Edit .env — VITE_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:5173.

Full step-by-step walkthrough: [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md).

### 7.4 First admin login

1. Set `BOOTSTRAP_ADMIN_EMAIL` in `backend/.env` to an email you control.
2. Save your Firebase service-account JSON to `backend/secrets/firebase-service-account.json` (git-ignored).
3. Start the backend, sign in on the frontend with that email via Firebase Auth.
4. Your profile is auto-created as `SUPER_ADMIN` + `approved`.
5. Approve subsequent users via Super Admin dashboard → Pending Approvals.

---

## 8. Configuration (environment variables)

### 8.1 Backend (`backend/.env`)

Copy from `backend/.env.example`. Never commit `.env` or `secrets/`.

| Variable | Required | Default / example | Purpose |
|---|---|---|---|
| `FIREBASE_PROJECT_ID` | Yes | `your-firebase-project-id` | Firebase project for Auth + Firestore |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Yes | `secrets/firebase-service-account.json` | Admin SDK credentials (server only) |
| `FIREBASE_STORAGE_BUCKET` | For uploads | `your-firebase-storage-bucket` | File + template storage bucket |
| `FIREBASE_EMULATOR_HOST` | No | _(empty)_ | Only when using Firebase Emulator Suite |
| `BOOTSTRAP_ADMIN_EMAIL` | Yes (first run) | `you@example.com` | First login with this email → `SUPER_ADMIN` |
| `ENVIRONMENT` | Yes | `development` | `development` \| `production` (hardening differs) |
| `CORS_ORIGINS` | Yes | `http://localhost:5173,http://127.0.0.1:5173` | Allowed frontend origins (no `*` in prod) |
| `ALLOWED_HOSTS` | Yes | `localhost,127.0.0.1` | Trusted hosts (real domain in prod) |
| `MAX_UPLOAD_SIZE_BYTES` | No | `10485760` (10 MiB) | Upload size cap |
| `BLOCKED_UPLOAD_EXTENSIONS` | No | `.exe,.bat,.cmd,.sh,.msi,.com,.dll,.scr,.jar` | Blocked upload types |
| `AI_PROVIDER` | No | `stub` | `stub` (placeholder) \| `gemini` (real drafting) |
| `GEMINI_API_KEY` | If `AI_PROVIDER=gemini` | _(empty)_ | Google AI API key |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model ID |

Legacy SQL variables (`DATABASE_URL`, `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `DEV_LOGIN_ENABLED`, `STORAGE_PROVIDER`, …) are **not** read by the active Firebase config (`app/core/config.py`) and are documented only for the archived path.

### 8.2 Frontend (`frontend/.env`)

Copy from `frontend/.env.example`. `VITE_*` values are **baked at build time**.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `VITE_API_URL` | Yes | `http://localhost:8000` | Backend base URL (build arg in Docker) |
| `VITE_DEV_LOGIN_ENABLED` | No | `true` (local), `false` (prod image) | Shows dev-login panel; real gate is backend-side |

---

## 9. Usage walkthrough

**As an Innovator:**

1. Log in → you land on `/innovator`.
2. Create a team, then create a patent inside it.
3. Open `/innovator/patents/:id` → fill **Basic Info** (applicants/inventors) → fill **Questionnaire** → upload supporting files → **Submit**.
4. Track status; respond to agent comments; check Calendar and Reports.

**As a Patent Agent:**

1. Log in → `/agent` shows the assignment queue (`Awaiting decision` vs rest).
2. Accept (or decline with reason) an assignment.
3. Open `/agent/patents/:id/draft` → generate sections (`Abstract`, `Background`, `Summary`, `Description`, `Claims`) → review versions → generate DOCX → collaborate via comments/files/calendar.

**As an Admin / Super Admin:**

1. `/admin` → All Patents, Templates; `/super-admin` → Pending Approvals, RBAC Matrix, All Users, Templates, Report Permissions.
2. Approve/reject users, assign/reassign agents (auto-assign picks the least-loaded approved agent), manage `.docx` templates, export reports.

---

## 10. API overview

Active routers are mounted in `backend/app/main.py` (`/api/auth` + `/api`). Full catalog with auth requirements: [`docs/API_OVERVIEW.md`](./docs/API_OVERVIEW.md).

Highlights:

- `GET /health` — Firebase probe (`200 ok` / `503 degraded`).
- `GET /api/auth/me`, `POST /api/auth/sync`, `POST /api/auth/logout`, `GET /api/auth/pending-users`, `POST /api/auth/users/{uid}/approve|reject`.
- `GET/POST /api/teams`, `GET/PATCH /api/teams/{id}`, member add/remove.
- `GET/POST /api/patents`, `GET/PATCH /api/patents/{id}`, `POST .../submit`, `.../assign|reassign|auto-assign`, `.../assignment/accept|reject`.
- `GET/PATCH/POST /api/patents/{id}/questionnaire…`, `POST .../draft/generate`, `GET .../draft…`.
- `GET/POST /api/patents/{id}/files…`, `.../documents…`, applicants/inventors/comments/calendar-events CRUD + reorder.
- `GET /api/notifications…`, `GET /api/calendar/events`, `GET/POST /api/templates…`, `GET /api/reports…`, `GET/POST /api/rbac…`.

Authenticated calls require `Authorization: Bearer <Firebase ID token>`.

---

## 11. Development

See [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) and [`CONTRIBUTING.md`](./CONTRIBUTING.md) for the full guide. Essentials:

```powershell
# Backend checks (from backend/)
python -m compileall app
pip install -r requirements.txt
python -m pytest -q

# Frontend checks (from frontend/)
npm ci
npm run lint
npm run build
```

Conventions: TypeScript `strict` + `noUnusedLocals`; functional React components; named exports; colocate route guards via `ProtectedRoute`; backend role guards via `require_roles` / `is_admin`; never commit `.env` or `secrets/`.

---

## 12. Testing

| Suite | Command | Notes |
|---|---|---|
| Backend (pytest) | `cd backend; python -m pytest -q` | `pytest.ini` sets `asyncio_mode=auto`. Current `tests/` target the **legacy SQL API** (`dev-login`, Postgres `TRUNCATE`) and need Postgres + legacy mounts — Firebase-path tests are a tracked gap (see `CHANGELOG.md` Unreleased). |
| Frontend build | `cd frontend; npm run build` | Runs `tsc -b && vite build` — type-check + bundle. |
| Frontend lint | `cd frontend; npm run lint` | `eslint .` (no custom config — default). |
| CI | GitHub Actions `ci.yml` | Backend compile + pytest, frontend lint + build, on `ubuntu/windows/macos`. |
| Docker | `docker.yml` + `docs/DOCKER.md` | Image builds + backend `/health` smoke test. |

---

## 13. Docker

| Image | Dockerfile | Run |
|---|---|---|
| Backend | `backend/Dockerfile` | `docker build -t patent-backend ./backend` → `docker run -p 8000:8000 --env-file backend/.env patent-backend` |
| Frontend | `frontend/Dockerfile` | `docker build --build-arg VITE_API_URL=https://api.example.com -t patent-frontend ./frontend` → `docker run -p 8080:80 patent-frontend` |
| Compose | `docker-compose.yml` | `docker compose up --build` (postgres + backend) |

Details, env mapping, and production notes: [`docs/DOCKER.md`](./docs/DOCKER.md).

---

## 14. Deployment

Full guide: [`DEPLOYMENT.md`](./DEPLOYMENT.md) (Koyeb + Neon + R2 history, env checklist, scale notes, verification steps).

Production checklist (enforced by `app/core/startup_checks.py` on the legacy path; apply manually for Firebase):

- `ENVIRONMENT=production`, real random `JWT_SECRET`/`SESSION_SECRET` (≥32 chars, distinct) where applicable.
- Real Google/Firebase credentials, `https://` `FRONTEND_URL` / `GOOGLE_REDIRECT_URI` / `CORS_ORIGINS` / `ALLOWED_HOSTS`.
- `STORAGE_PROVIDER=r2` (legacy) or Firebase Storage bucket (active) — never `local` in production.
- One backend replica (rate limiting is in-memory; migrations race with multiple replicas).
- Health check: `GET /health` → `200` + `x-content-type-options`, `x-frame-options`, `x-request-id`.

---

## 15. Documentation index

| Document | Purpose |
|---|---|
| [`docs/GETTING_STARTED.md`](./docs/GETTING_STARTED.md) | First-run tutorial, Firebase setup, login |
| [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md) | Symptom-first fixes (ports, auth, Docker, CI) |
| [`docs/FAQ.md`](./docs/FAQ.md) | Short answers to repeated questions |
| [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | System diagram, auth model, Firestore collections, state machine, AI providers |
| [`docs/decisions/`](./docs/decisions/) | Architecture Decision Records (ADR-001 Firebase runtime, ADR-002 roles, ADR-003 single instance, ADR-004 stub-first AI) |
| [`docs/API_OVERVIEW.md`](./docs/API_OVERVIEW.md) | Endpoint catalog with methods, auth, and payloads |
| [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md) | Dev workflow, code style, scripts, common errors |
| [`docs/DOCKER.md`](./docs/DOCKER.md) | Docker + Compose reference |
| [`backend/README.md`](./backend/README.md) | Firebase backend setup + endpoint list |
| [`DEPLOYMENT.md`](./DEPLOYMENT.md) | Production deployment guide |
| [`CHANGELOG.md`](./CHANGELOG.md) | Release history |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | How to contribute |
| [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) | Community standards |
| [`SECURITY.md`](./SECURITY.md) | Vulnerability reporting + hardening |
| [`ACCESSIBILITY.md`](./ACCESSIBILITY.md) | Accessibility commitments + gaps |
| [`SUPPORT.md`](./SUPPORT.md) | Getting help |
| [`AGENTS.md`](./AGENTS.md) | Agent-oriented repo instructions (commands, conventions, boundaries) |
| [`CITATION.cff`](./CITATION.cff) | How to cite this project |

---

## 16. Contributing

We welcome issues, docs improvements, bug fixes, and features. Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) first — it covers:

- Good-first-issue workflow, branch naming, conventional commits.
- Backend + frontend setup, required checks (`pytest`, `tsc`, `eslint`, Docker build).
- PR process (template, linked issues, screenshots for UI, no secrets).

By contributing you agree to abide by the [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

---

## 17. Code of Conduct

This project follows the **Contributor Covenant v2.1**. Be kind, be respectful, assume good faith. Enforcement is described in [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

---

## 18. Security

If you find a vulnerability, **do not open a public issue**. Follow [`SECURITY.md`](./SECURITY.md) (private report, what to include, response timeline, supported versions, hardening notes).

---

## 19. Accessibility

We target **WCAG 2.2 AA** for the frontend. Scope, keyboard support, known gaps (FullCalendar density, PDF canvas, color-contrast debt), and how to report barriers: [`ACCESSIBILITY.md`](./ACCESSIBILITY.md).

---

## 20. Support

- Questions / ideas: [GitHub Discussions](https://github.com/auraflaa/patent_drafting_tool/discussions) (or open a docs issue).
- Bugs: [issue tracker](https://github.com/auraflaa/patent_drafting_tool/issues) with the Bug template.
- Response expectations and troubleshooting: [`SUPPORT.md`](./SUPPORT.md).

---

## 21. Changelog

See [`CHANGELOG.md`](./CHANGELOG.md) (Keep a Changelog format). Unreleased section tracks the Firebase migration validation and test-suite alignment work.

---

## 22. License

Apache-2.0 — see [`LICENSE`](./LICENSE).

```text
Copyright 2026 auraflaa and patent_drafting_tool contributors.
SPDX-License-Identifier: Apache-2.0
```

---

## 23. Acknowledgements

- Built with FastAPI, React, Vite, Firebase, Firestore, and Cloud Storage.
- DOCX pipeline via `python-docx`; PDF conversion via LibreOffice in Docker.
- Calendar via FullCalendar, charts via Recharts, PDF preview via react-pdf.
- Thanks to all contributors — see commit history.
