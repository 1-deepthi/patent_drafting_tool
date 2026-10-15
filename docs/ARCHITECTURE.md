# Architecture

## 1. System overview

```text
                    +------------------+
                    |   React + Vite   |
                    |   frontend/:5173 |
                    |  (nginx in prod) |
                    +--------+---------+
                             |  HTTPS / JSON + multipart
                             |  Authorization: Bearer <Firebase ID token>
                             v
                    +--------+---------+
                    |  FastAPI backend |
                    |  backend/:8000   |
                    |  app/main.py     |
                    +--------+---------+
                             |
            +----------------+----------------+
            |                |                |
   Firebase Auth      Cloud Firestore    Cloud Storage
   (verify ID token)  (all app data)     (files, templates,
                                          generated docs)
```

- **Frontend** (`frontend/`): React 18 SPA, React Router role-guarded routes, React Query data fetching, Hook Form + Zod validation. Build-time `VITE_API_URL`; no runtime env.
- **Backend** (`backend/app/main.py`): FastAPI with `lifespan` that attempts `initialize_firebase()` but never blocks boot; `/health` probes Firestore. Mounts exactly two routers: `auth` (`/api/auth`) and `resources` (`/api`). CORS + TrustedHost middleware; generic 500 handler (verbose only outside production).
- **Firebase**: Authentication is the identity provider; Firestore is the system of record; Storage holds blobs. The Admin SDK runs privileged — Firestore Security Rules do **not** replace backend checks.

## 2. Request lifecycle

1. Client signs in via Firebase Auth (Google / Email) and holds an **ID token**.
2. `src/lib/api.ts` (`apiFetch`) attaches `Authorization: Bearer <token>` to every authenticated call.
3. `app/core/security.py:current_user` verifies the token (`verify_id_token(check_revoked=True)`), loads or auto-creates `users/{uid}`, and enforces the bootstrap-admin upgrade.
4. `active_user` rejects non-`approved` accounts (`403 awaiting approval`).
5. `require_roles(*roles)` / `is_admin()` enforce RBAC per endpoint.
6. `app/services/repository.py` helpers (`get_doc`, `list_docs`, `create_doc`, `patch_doc`, `delete_doc`) scope reads/writes to visible docs (admin bypass, else creator/owner/member/assignee match).

## 3. Roles and auth model

| Role code | Granted by | Meaning |
|---|---|---|
| `INNOVATOR` | Default for new users | Own teams + patents |
| `PATENT_AGENT` | `ADMIN`/`SUPER_ADMIN` via `/api/rbac/users/{id}/roles` | Can be assigned patents |
| `ADMIN` | `SUPER_ADMIN` | Approve users, assign agents, manage templates |
| `SUPER_ADMIN` | Bootstrap email, then `SUPER_ADMIN` only | Full control incl. role assignment |

- Roles are stored as a `role_codes: string[]` array on the user document (not custom claims).
- `account_status`: `pending` → `approved` (or `rejected`). Only `approved` passes `active_user`.
- Frontend mirrors this in `AuthContext` (`loading | unauthenticated | pending | approved`) with a sliding 30-minute refresh (`POST /api/auth/refresh` on the legacy path; Firebase tokens refresh client-side in the active path).
- Route guards: `ProtectedRoute(requireRole=[...], requirePermission=...)` → redirects to `/login`, `/pending-approval`, or `/not-authorized`.

## 4. Firestore collections

No joins, no migrations — documents linked by string IDs:

| Collection | Key fields | Linked by |
|---|---|---|
| `users` | `role_codes[]`, `account_status`, `approved_by/at` | `uid` (doc ID) |
| `teams` | `owner_uid`, `member_uids[]`, `created_by` | `created_by` / membership |
| `patents` | `status`, `workflow_status`, `assigned_agent_uid`, `assignment_status` | `owner_uid` / `created_by` / `assigned_agent_uid` |
| `applicants`, `inventors` | `patent_id`, `display_order` | `patent_id` |
| `questionnaires` | doc ID = `patent_id`, `status`, `answers{}` | `patent_id` |
| `questionnaire_versions` | `patent_id`, snapshot | `patent_id` |
| `draft_sections` | `patent_id`, `section_type`, `version`, `content` | `patent_id` |
| `documents` | `patent_id`, `document_type`, `version`, `storage_path` | `patent_id` |
| `files` | `patent_id`, `storage_path`, `uploaded_by` | `patent_id` |
| `comments` | `patent_id`, `author_uid` | `patent_id` |
| `calendar_events` | `patent_id?`, `created_by`/`owner_uid`, `event_type` | user or patent |
| `notifications` | `recipient_uid`, `read` | recipient |
| `templates` | `document_type`, `is_active`, `storage_path` | type (one active per type) |

Probe collection `_health` is used only by `/health`.

## 5. Patent state machine

Active Firebase fields: `status` / `workflow_status` (`draft`, `submitted`, `under_review`) plus assignment (`pending`, `accepted`, `rejected`).

```text
create (draft) → submit (submitted) → assign (assignment pending)
  → accept (accepted, workflow under_review)
  → reject (rejected, assigned_agent cleared) → reassign
```

Guards in `app/api/resources.py`:

- `submit`: owner or admin only.
- `assign` / `reassign` / `auto-assign`: `ADMIN`/`SUPER_ADMIN` only; assignee must be an approved `PATENT_AGENT`; auto-assign picks the lowest `active_assignment_count`.
- `PATCH /patents/{id}`: blocks edits once `submitted`/`under_review`/`approved` for non-admin/non-agent callers; strips protected fields (`id`, `created_by`, `owner_uid`, `assigned_*`, `workflow_status`, `status`).
- Questionnaire `submit` flips questionnaire `status` to `submitted` (draft generation gating lives in legacy `draft_service.can_generate`).

Legacy full lifecycle (`Draft … Granted/Rejected/Withdrawn/Abandoned`, 17 states in `app/models/patent.py`) is **not enforced** in the active path — tracked as migration debt.

## 6. AI drafting providers

`app/services/ai/` — Strategy pattern:

- `base.AIProvider` ABC → `stub_provider` (default placeholder, clearly labeled, plus `warning: not legal advice`) and `gemini_provider` (Google `generativeai`, model `GEMINI_MODEL`, requires `GEMINI_API_KEY`).
- `factory.get_ai_provider()` returns Gemini only when `AI_PROVIDER=gemini` **and** a key is set; otherwise stub.
- `POST /api/patents/{id}/draft/generate {section_type}` saves to `draft_sections` with incremented `version`.

## 7. Documents and files

- **Documents**: `POST .../documents/generate` builds a DOCX via `python-docx` (Basic Info + Questionnaire answers), uploads to `patents/{pid}/documents/...`, records a `documents` doc (`status: completed, version: 1`). Download via signed v4 URL (300 s). Retry re-generates the same `document_type`. DOCX→PDF conversion shells out to headless LibreOffice (Docker image only).
- **Files**: `POST .../files` (multipart) validates non-empty, size cap, and blocked extensions, then uploads to `patents/{pid}/files/{uuid}_{name}` + `files` doc. Download via signed URL; delete removes both blob and doc (uploader or admin only).
- **Templates**: `POST /api/templates` (admin only, multipart `.docx`) → `templates/{type}/{uuid}_{name}` + `templates` doc; `.../activate` deactivates siblings of the same `document_type`.

## 8. Legacy Postgres path (reference only)

Present but unmounted: `app/models/*` (24 SQLAlchemy tables), `alembic/`, 13 routers (`ai`, `basic_info`, `calendar`, `comments`, `documents`, `files`, `notifications`, `patents`, `questionnaire`, `rbac`, `reports`, `teams`, `templates`), `app/services/*` SQL services, `app/core/{database,oauth,startup_checks,rate_limit,middleware,logging_config}.py`, and `tests/` targeting `/api/auth/dev-login` + Postgres `TRUNCATE`.

Do not build new features on it. Do not deploy it. Removal requires an approved migration-completion issue.

## 9. Frontend architecture

- Entry `index.html` → `src/main.tsx` (`QueryClientProvider` + `StrictMode`) → `src/App.tsx` (`BrowserRouter` + `AuthProvider` + role routes).
- `ROLE_HOME` maps first matching role to its dashboard.
- Data flow: pages → `apiFetch`/`apiUpload`/`apiDownload` → React Query (where used) → `StatusBadge` / `DashboardShell` / panels.
- 14 pages (4 dashboards + workflow + draft workspace + admin patent list/detail + calendar + reports + auth quartet) and 8 shared components (see README §6 and `API_OVERVIEW.md` for endpoint usage per page).

## 10. Cross-cutting concerns

- **Config**: `app/core/config.py` (`pydantic-settings`, `.env`, `extra='ignore'`) — Firebase + app + upload + AI settings only.
- **Observability**: global 500 handler, request logging via uvicorn/gunicorn access logs; structured Loguru JSON and `RequestID`/`SecurityHeaders` middleware exist in legacy `core/` but are not wired in active `main.py` (gap).
- **Scaling**: single-instance assumption — in-memory rate limiting and boot-time migrations race with multiple replicas. See `DEPLOYMENT.md` "A note on scale".
