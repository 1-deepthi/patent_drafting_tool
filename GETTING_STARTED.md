# Getting Started — Phase 1 + 2 + 3 + 4 + 5 + 6 + 7 Complete

Phase 1 (scaffolding), Phase 2 (database schema & models), Phase 3 (Auth &
RBAC), Phase 4 (Teams & Patent Applications), Phase 5 (Basic Information &
Questionnaire — backend AND frontend), Phase 6 (AI drafting, backend AND a
frontend workspace), and Phase 7 (document generation, backend AND a
frontend panel) are done. Phases 1–5 and 7 are live-verified against a real
PostgreSQL database, a real FastAPI dev server, and (for Phase 7) real
LibreOffice DOCX→PDF conversion. Phase 6's HTTP-layer flow (gating,
versioning, visibility) is equally live-verified — but only against the
built-in **stub** AI provider, not real Gemini; see the Phase 6 section
below for exactly what that does and doesn't cover. Phase 7's storage layer
is verified against the local filesystem provider only, not real Cloudflare
R2 — see the Phase 7 section for why.

## Phase 7 — Document generation (NEW this session)

### What was built
- **`app/services/storage/`** — a storage abstraction mirroring Phase 6's
  AI Provider Interface pattern: `base.py` defines the abstract
  `StorageProvider` (`save`/`load`/`delete`, all key-based);
  `local_provider.py` is the offline-safe default (writes under
  `./storage_data` on the API's own filesystem — fine for this sandbox,
  NOT fine for a real multi-instance deployment since Koyeb instances
  don't share a disk); `r2_provider.py` is a real implementation against
  R2's S3-compatible API via `boto3`; `factory.py` picks between them via
  `STORAGE_PROVIDER` in `.env` (`local` default, or `r2`).
- **`app/services/document_service.py`** — assembles the patent's 5
  AI-drafted sections (Phase 6's `AIOutput` rows) into a DOCX via
  `python-docx` with a bold red "DRAFT — NOT FOR FILING" banner (dropped
  once `application_status` reaches `"Granted"`), optionally converts to
  PDF by shelling out to headless LibreOffice (`soffice --headless
  --convert-to pdf`), and drives the whole thing as a tracked
  `DocumentGenerationJob`: Processing → Completed (with new `Document` +
  `DocumentVersion` rows) or Failed (nothing linked in, error recorded).
  Runs synchronously inside the request — same incremental choice as
  Phase 6's AI generation, per `config.py`'s existing Celery/Redis note.
  `DOCUMENT_TYPES` is a single jurisdiction-agnostic type for now (open
  item #1 is still unresolved); Admin/Super Admin can define real
  `Template` rows for other types later, but none exists out of the box in
  this phase — generation always falls back to a plain layout.
- **`app/api/documents.py`** — endpoints nested under
  `/api/patents/{id}/documents`:
  - `GET /documents` / `GET /documents/{id}/versions` — list documents and
    their version history for a patent.
  - `POST /documents/generate` — body `{"output_format": "PDF"|"DOCX"}`;
    only the assigned Patent Agent or an Admin/Super Admin may call it,
    and **DOCX is Patent-Agent-only** (Admin is restricted to PDF).
    Gated on `can_generate_documents()`: status must be `"Under Review"`
    or `"Draft Generated"` (the latter allows regenerating) AND every one
    of Phase 6's 5 sections must have a `Completed` `AIOutput` — checked
    and raised as a 400 **before** any job row is created, matching how
    `ai.generate_draft` handles its own gate.
  - `GET /documents/jobs`, `GET /documents/jobs/{id}` — job history and
    single-job status.
  - `POST /documents/jobs/{id}/retry` — only for a `Failed` job; always
    creates a **brand-new** job row (`retried_from_job_id` points at the
    original), never resumes. The original failed job is left untouched.
  - `GET /documents/{id}/download`, `GET /documents/versions/{id}/download`
    — stream the stored file back with the right `Content-Type` and
    `Content-Disposition` (any past version stays downloadable, even after
    a newer one is generated).
  - On a successful generation, `application_status` advances
    `"Under Review"` → `"Draft Generated"` automatically (new Phase 7
    decision — flag if this shouldn't be automatic), and the Innovator who
    created the patent gets a `DraftGenerated` notification.
- **`app/core/config.py`** — added `storage_provider` (default `"local"`),
  `local_storage_path`, and `libreoffice_binary`/`libreoffice_timeout_seconds`.
- **Frontend**: `frontend/src/components/DocumentGenerationPanel.tsx`,
  rendered at the bottom of the existing `/agent/patents/:id/draft`
  workspace (no new route — document generation is part of the same
  Agent workflow as AI drafting). "Generate PDF" / "Generate DOCX"
  buttons (disabled with an explanation until every section is
  `Completed` and the status allows it), the latest document with a
  DRAFT badge and a "Download latest" link, an expandable per-document
  version history with per-version downloads, and a generation-job
  history list with a "Retry" button on any `Failed` job. Added
  `apiDownload()` to `lib/api.ts` for binary (non-JSON) downloads, since
  `apiFetch` always parses JSON. `tsc -b` and `npm run build` both clean.

### Live verification performed
Fresh Postgres + fresh `uvicorn` server this session, LibreOffice
confirmed installed and used for real (unlike Gemini/R2, this sandbox's
egress allowlist has no issue here — LibreOffice runs locally, no network
needed). Drove the full HTTP flow: team → patent → basic info →
questionnaire → submit → assign → accept → confirmed generation is
blocked with 400 and the exact "must be completed for every section"
reason before any AI drafting exists → generated all 5 AI sections (stub
provider) → confirmed Innovator gets 403 attempting to generate documents
→ confirmed Admin gets 403 selecting DOCX → generated as the agent with
`output_format: PDF` → confirmed job `Completed`, `application_status`
advanced to `"Draft Generated"`, a `Document` row exists with
`watermark_status: "DRAFT"`, downloaded the actual file and confirmed real
`%PDF-` magic bytes and `application/pdf` content-type → regenerated as
DOCX → confirmed a second `DocumentVersion` exists, the latest download is
now a real DOCX (`PK` zip magic bytes), and **version 1 is still
downloadable and still the original PDF** → confirmed job history and
single-job-by-id fetch → confirmed retrying a `Completed` job is rejected
with 400.

Separately, deliberately broke `LIBREOFFICE_BINARY` to point at a
non-existent binary and re-ran against a fresh patent: confirmed a PDF
request fails cleanly as a `Failed` job (no `Document` row created),
confirmed retry creates a **new** job id linked via `retried_from_job_id`
to the original (also `Failed`, since the binary was still broken), and
confirmed the original failed job is preserved unchanged. This caught and
fixed a real bug: the internal `rollback()` on failure was expiring other
ORM objects (`user`, `patent`) still referenced later in the request,
and touching their attributes afterward crashed with `MissingGreenlet`
outside an awaited context — fixed by capturing `user.id`/`patent.id` as
plain primitives before the job runs, rather than re-reading expired ORM
attributes after.

### What is genuinely NOT verified — read this before relying on R2
Same situation as `gemini_provider.py` in Phase 6: this sandbox's network
egress allowlist doesn't include Cloudflare R2's endpoint domain, so
`r2_provider.py` has **never been executed against a live bucket.** It's
written carefully against R2's documented S3-compatible surface via
`boto3`, but treat it as reviewed-but-untested. To try it for real: set
`STORAGE_PROVIDER=r2` and the four `R2_*` settings in `.env` and restart —
everything else (job tracking, versioning, endpoints, frontend) works
unchanged, only the storage provider swaps.

### Not done this session (carry into the next phase)
- No real `Template` merging — `Template.file_path` (a stored template
  with its own letterhead/styling) isn't read or merged against yet; every
  document uses the same plain generated layout regardless of any
  `Template` row that might exist. A Templates management UI for
  Admin/Super Admin (create/version/activate templates) also doesn't
  exist yet.
- No cleanup job for orphaned storage objects — `cleanup_status` is
  tracked on the job (`"Cleaned"` on success, `"Pending"` on failure) but
  nothing actually sweeps a `Pending` file out of storage; this only
  matters once a real multi-tenant storage backend (R2) is in use, since
  the local provider's files just sit on disk.
- Watermarking is a bold red text banner in the DOCX, not a true
  diagonal/rotated stamp — simpler, but flag if the real spec wants an
  actual diagonal watermark image.
- No manual editing of the generated document before it's finalized —
  generation is fully automatic from the latest `AIOutput` per section;
  incorporating Agent hand-edits into a document version isn't built.



## Phase 6 — AI drafting (NEW this session)

### What was built
- **`app/services/ai/`** — the AI Service Layer / Provider Interface called
  for in the spec: `base.py` defines the abstract `AIProvider` (one method,
  `generate(prompt) -> (text, input_tokens, output_tokens)`); `stub_provider.py`
  is a deterministic, offline-safe placeholder used by default;
  `gemini_provider.py` is a real REST implementation against Google's
  Generative Language API (no extra SDK — plain `httpx`); `factory.py` picks
  between them based on `AI_PROVIDER` in `.env` (`stub` default, or `gemini`).
  Swapping providers touches zero lines outside this folder.
- **`app/services/draft_service.py`** — the actual drafting logic: 5
  jurisdiction-agnostic sections (`ABSTRACT`, `BACKGROUND`, `SUMMARY`,
  `DESCRIPTION`, `CLAIMS` — deliberately avoiding office-specific headings
  since jurisdiction is still an open decision, see handover open item #1),
  prompt-building from the **latest submitted `QuestionnaireVersion`**
  (never the live, possibly-mid-edit `Questionnaire` row), and
  `can_generate()` gating: drafting is only allowed once
  `application_status == "Under Review"` (i.e. the assigned Patent Agent has
  accepted) and at least one questionnaire version has been submitted.
- **`app/api/ai.py`** (matches the placeholder comment already in
  `main.py` from the Phase 5 session) — endpoints nested under
  `/api/patents/{id}/draft`:
  - `GET /draft` — one slot per section type, `latest: null` if never
    generated.
  - `POST /draft/generate` — body `{"section_types": [...] | null}`; null/
    omitted regenerates every section, a subset regenerates just those.
    Only the assigned Patent Agent or an Admin/Super Admin may call this.
  - `GET /draft/{section_type}/versions` — full regeneration history for
    one section.
  - Every generation call **appends a new `AIOutput` row** rather than
    overwriting — same versioning convention as `QuestionnaireVersion`,
    and it's the schema `ai_outputs` (from the Phase 2 migration) was
    already built for: `UniqueConstraint(questionnaire_version_id,
    section_type, version_number)`. **No new migration was needed** — this
    table already existed from Phase 2's initial 24-table schema and had
    simply never been used yet.
- **`app/core/config.py`** — added `ai_provider` (default `"stub"`) and
  `gemini_model` settings alongside the pre-existing `gemini_api_key`.
- **Frontend**: `frontend/src/pages/DraftWorkspacePage.tsx` at
  `/agent/patents/:id/draft`, linked from each of the agent's applications
  on `AgentDashboard.tsx` ("AI Drafting" button). Shows all 5 sections,
  "Generate all" and per-section "Generate/Regenerate" buttons (disabled
  once the application is out of "Under Review"), the latest content and
  processing status per section, and an expandable version-history list per
  section. `tsc -b` and `npm run build` both clean.

### Live verification performed (stub provider)
Fresh Postgres + fresh `uvicorn` server this session (neither persists
between chats). Drove the exact HTTP calls the new UI makes: Innovator
creates team/patent/applicant/inventor, fills and submits the questionnaire
→ confirmed draft generation is blocked with 403 before an agent is even
assigned (caller isn't the assigned agent) → assigned + attempted generation
as the not-yet-accepted agent → confirmed blocked with 400 and the exact
"only available once...accepted" reason string → agent accepts → confirmed
`GET /draft` returns all 5 section slots with `latest: null` → generated all
5 sections in one call → confirmed all 5 came back `Completed`, all at
`version_number == 1`, `ai_provider == "stub-provider"` → regenerated just
`CLAIMS` → confirmed it advanced to `version_number == 2` while every other
section stayed at `v1`, confirmed via both the summary endpoint and
`GET /draft/CLAIMS/versions` (2 entries) → confirmed an unknown
`section_type` is rejected with 422 → confirmed the Innovator can read the
draft (same visibility rule as the parent patent) but gets 403 attempting to
trigger generation.

### What is genuinely NOT verified — read this before relying on Gemini
This sandbox's network egress allowlist does not include
`generativelanguage.googleapis.com`, so **`gemini_provider.py` has never
actually been executed against a live Gemini endpoint.** It's been written
carefully against the documented request/response shape (`contents` /
`candidates[0].content.parts[0].text` / `usageMetadata`), but treat it as
reviewed-but-untested code, not verified code, until someone runs it with a
real `GEMINI_API_KEY` and confirms:
- The response parsing (`candidates[0]["content"]["parts"][0]["text"]`)
  matches what the API actually returns today.
- Error handling for rate limits, content-safety blocks, and timeouts is
  adequate (currently: any `httpx.HTTPError` or unexpected shape is caught
  and surfaces as a `Failed` `AIOutput` row with the exception text as
  `ai_response` — reasonable, but never exercised against a real failure).
- Token usage fields (`promptTokenCount`/`candidatesTokenCount`) are named
  correctly for the model version actually in use.

To try it for real: set `AI_PROVIDER=gemini` and `GEMINI_API_KEY=...` in
`.env`, restart the backend, and everything else (gating, versioning,
endpoints, frontend) should work unchanged — only the provider swaps.

### Not done this session (carry into the next phase)
- No background job / async queue — generation runs synchronously inside
  the request, same incremental approach as the rest of the project so far
  (Redis/Celery explicitly deferred per `config.py`'s existing comment).
  Fine for a single Gemini call per section today; revisit if Phase 7's
  `DocumentGenerationJob` needs a shared job-queue pattern and it makes
  sense to backfill this too.
- No retry/backoff on provider failures — a `Failed` row is left as-is;
  the Agent has to click "Regenerate" again by hand.
- No cost/usage dashboard, even though `input_tokens`/`output_tokens` are
  captured per row — they're stored but nothing aggregates or displays them
  yet.
- Manual editing of AI-generated text isn't part of this phase — per the
  Phase 2 schema, `ai_outputs.ai_response` is the raw model output and isn't
  meant to be hand-edited; incorporating Agent edits belongs to Phase 7's
  `Document`/`DocumentVersion` tables when the actual filed document is
  assembled from a section's latest `AIOutput` plus template + edits.



## Phase 5 frontend — NEW this session

- **`frontend/src/pages/PatentWorkflowPage.tsx`** — new page at
  `/innovator/patents/:id`, linked from each patent card on the Innovator
  dashboard ("Basic Info & Questionnaire" while in Draft, "View" afterward).
  Two tabs:
  - **Basic Information**: Applicants panel (add/edit/remove, primary
    toggle with server-side auto-unset, ↑/↓ reordering via
    `POST .../reorder`) and an equivalent Inventors panel. Both call the
    real Phase 5 endpoints directly — no mock data.
  - **Questionnaire**: Invention Type selector, then "About the
    Invention", "Technical Details" (this is where **`invention_type`
    branching** lives — `TECHNICAL_DETAILS_GUIDANCE` in `lib/types.ts`
    swaps the field's label/placeholder per type: Software/Mechanical/
    Electronics/Biotech/Chemistry; the DB still stores one shared
    `technical_description` column, per the Phase 2 schema), and
    "Additional Information" (advantages/prior_art/keywords/drawings
    checkbox, all optional). Each section has its own Save button
    (`PATCH` with just that section's fields — matches the backend's
    partial-update/autosave design without needing debounce logic).
    Also: live completion-percentage bar, Submit Questionnaire button,
    and a version-history viewer (`GET .../versions`).
  - The whole page respects **Draft-only editability** — read-only with
    an explanatory banner once the application is out of Draft, same
    convention as the existing title-edit rule.
- **Types**: `ApplicantOut/Input`, `InventorOut/Input`,
  `QuestionnaireOut`, `QuestionnaireUpdateInput`, `QuestionnaireVersionOut`,
  `INVENTION_TYPES`, `TECHNICAL_DETAILS_GUIDANCE` all added to
  `frontend/src/lib/types.ts`.
- **Routing**: `/innovator/patents/:id` added to `App.tsx` ahead of the
  existing `/innovator/*` wildcard, role-gated the same way as the rest of
  the Innovator routes.

### Verified this session
- `tsc -b` — clean.
- `npm run build` (Vite production build) — clean, 93 modules, no warnings.
- **Live end-to-end run** against a real PostgreSQL 16 instance + real
  `uvicorn` server (Postgres installed fresh this session — doesn't persist
  between chats, same as every prior phase): dev-login as an Innovator →
  create team → create patent → confirm submit blocked (nothing filled) →
  create 2 applicants with the exact JSON shape the new
  `ApplicantsPanel` sends → flip primary A→B, confirmed A auto-unset and
  exactly one primary remains → reorder applicants, confirmed persisted
  order → create inventor → confirm submit still blocked
  (questionnaire-only reason) → `GET` auto-creates questionnaire
  (`Not Started`) → `PATCH` each section exactly as
  `QuestionnaireTab.saveSection` does → confirm questionnaire-submit
  blocked while `technical_description` is missing, with the specific
  missing-field message the UI surfaces verbatim → fill it in, confirm
  `completion_percentage` math (5 of 8 completion-tracked fields = 62.5%,
  since the percentage is computed over all 7 text fields + invention_type,
  not just the 5 required-for-submit ones — worth knowing if the progress
  bar looks "stuck" below 100% even once every required field is filled) →
  submit questionnaire, confirms `v1` snapshot → edited a field on the
  now-Completed questionnaire, confirmed it reopens to `In Progress`
  exactly as documented → re-submitted, confirmed `v2` snapshot → patent
  submit now succeeds → confirmed both an Inventor-create and a
  Questionnaire-edit are correctly blocked (400) once the application is
  `Submitted`.
- No React Testing Library / Playwright browser test was run — verification
  above exercises the same HTTP calls the UI makes, but the rendered UI
  itself (layout, click targets, responsiveness) hasn't been eyeballed in
  a real browser.

### Not done this session (carry into the next phase)
- No read-only view of Basic Information/Questionnaire was built for
  Patent Agent or Admin/Super Admin roles — only the Innovator route
  exists. The backend already scopes visibility correctly; only the
  Innovator-facing route was added. Flag if Agent/Admin should also be able
  to open this page (read-only) from their own dashboards.
- Section-by-section "Save" is an explicit button per section, not a
  continuous debounce-on-type autosave — a deliberate simpler choice this
  session; revisit if true type-and-forget autosave is wanted.



- **Applicants & Inventors** (`backend/app/api/basic_info.py`), nested under
  `/api/patents/{id}/applicants` and `/api/patents/{id}/inventors` — full
  CRUD plus `POST .../reorder`. Editable only while the patent is `Draft`.
  Setting an applicant `is_primary=true` auto-unsets any other primary on
  the same application. `Applicant.display_order` is new this phase
  (migration `7bc9adf8f2ee_add_applicant_display_order.py`).
- **Questionnaire** (`backend/app/api/questionnaire.py`) — `GET` auto-creates,
  `PATCH` is a partial autosave-style update, `POST .../submit` validates
  required fields and writes a permanent version snapshot, `GET .../versions`
  lists history.
- **Submit-gating (new)**: `POST /api/patents/{id}/submit` now requires at
  least one Applicant (one primary), at least one Inventor, and a
  `Completed` questionnaire before allowing `Draft → Submitted`.
- Verified with a Python `httpx` script driving the full flow against a real
  running server — see `Project_Handover_v3.md` §7.5 for the exact sequence.
- Frontend for this backend was built in a later session — see the "Phase 5
  frontend — NEW this session" section above.

## Phase 4 — what's here and what's been verified

- **Teams** (`backend/app/api/teams.py`) — create, list (scoped to your
  own teams unless Admin/Super Admin), get detail with member list,
  update, add/remove members by email. Team creation is an Innovator
  action per spec; Admin/Super Admin get read-only oversight of all teams.
- **Patent Applications** (`backend/app/api/patents.py`) — create under a
  team, list/get (strictly scoped — see below), edit title (Draft only),
  submit (Draft → Submitted).
- **Agent assignment & the Accept/Reject flow** — manual assignment
  (Innovator picks from `/api/patents/available-agents`, sorted by active
  workload) or auto-assign (lightest workload, "fewest active
  assignments" rule). Only the assigned agent can accept/reject — verified
  that a different Patent Agent gets a 404, and that Admin/Super Admin
  cannot call the accept endpoint at all (role-gated) or reassign an
  already-accepted patent (state-gated), per spec item 12.
- **Visibility scoping — verified live with 4 real accounts**: a Patent
  Agent's list only contains applications assigned to them (confirmed a
  second, unassigned agent sees an empty list and gets 404 on direct GET);
  an Innovator sees applications for teams they belong to; Admin/Super
  Admin see everything. Cross-tenant access (an outsider Innovator hitting
  another team's ID) correctly 404s rather than 403 — doesn't confirm the
  team exists to non-members.
- **Reject → reassign cycle** — verified an agent rejecting an assignment
  correctly clears `assigned_patent_agent_id`, reverts status to
  `Submitted`, and makes the patent immediately reassignable.
- **Notifications & audit logs** — assignment/accept/reject/submit events
  write type-driven notification rows and `audit_logs` rows (no message
  text stored, per spec).
- **Frontend** — Innovator dashboard (team switcher, member management,
  patent creation/submission, agent picker with live workload counts) and
  Patent Agent dashboard (assignment queue with accept/reject). Both
  `tsc --noEmit` and `npm run build` are clean.

### What was assumed (flag if wrong)

- **Team membership is instant** (creator/Admin adds a user, they're in
  immediately) — no invite-and-accept step. Simpler default since no
  invite flow was specified.
- **Auto-assign picks the agent with the fewest currently-active
  assignments** (statuses outside Granted/Rejected/Withdrawn/Abandoned
  count as active).
- **No reassignment after an agent has accepted** — once accepted, only
  that agent's own accept/reject-equivalent actions (reject/request-change,
  built in later phases) can change who's assigned. Admin/Super Admin can
  freely assign/reassign *before* acceptance. Revisit if you want an
  explicit "Admin force-reassign" escape hatch for e.g. an agent going on
  leave — deliberately left out for now as the safer reading of "Admin can
  never override a Patent Agent's decision."

## Phase 3 — Auth & RBAC (unchanged from before)

- **Google OAuth 2.0 / OIDC** (`backend/app/core/oauth.py`,
  `backend/app/api/auth.py`) — the real, only-supported sign-in flow via
  Authlib: `GET /api/auth/google/login` → Google → `GET
  /api/auth/google/callback` → matches/creates the user → issues a JWT →
  redirects to `FRONTEND_URL/auth/callback?token=...`. Requires real
  `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env` to actually complete
  (see "Google OAuth credentials" below) — the code path itself was
  exercised up to Google's own metadata endpoint, which is as far as it
  can go without real credentials and outbound access to accounts.google.com.
- **Dev-login bypass** (`POST /api/auth/dev-login`) — hard-gated behind
  `ENVIRONMENT=development` **and** `DEV_LOGIN_ENABLED=true`; returns a
  plain 404 otherwise (doesn't even hint the route exists). Lets you
  exercise every RBAC path without Google credentials. **Verified live**:
  logging in as the seeded bootstrap Super Admin correctly claims the
  Phase 2 placeholder account (no duplicate created); creating a new email
  creates a fresh `Approved` dev user with the requested role; flipping
  `DEV_LOGIN_ENABLED=false` and restarting correctly 404s the endpoint.
- **Stateless JWT sessions**, 30-minute sliding-expiry inactivity timeout
  — no sessions table, per product decision. The frontend calls
  `POST /api/auth/refresh` on a 1-minute timer *only* while the user has
  been active in the last 30 minutes, so genuinely idle sessions expire
  naturally via the JWT's own `exp` claim. Verified: `/refresh` mints a
  new token; an expired/invalid token gets a clean 401.
- **Pending-approval gating** — new accounts (real Google or dev-login
  creating a brand-new user via the real OAuth path) start `Pending`.
  `GET /api/auth/me` works for *any* authenticated user regardless of
  status (so the frontend can show the pending screen); every other
  protected endpoint requires `Approved` and returns a 403 explaining why
  otherwise. Verified live with a manually seeded `Pending` user.
- **Role & Permission management dashboard** (`backend/app/api/rbac.py`,
  `frontend/src/pages/SuperAdminDashboard.tsx`) — full V1 feature:
  Super-Admin-only endpoints to view/toggle the role↔permission grant
  matrix, list all users, and assign/revoke roles per user. Verified live:
  toggling a grant immediately changes what a *different, already logged
  in* user's `/me` reports as their permissions; a Super Admin cannot
  revoke their own Super Admin role (self-lockout guard).
- **Account approval endpoints** — `GET /api/auth/pending-users`,
  `POST /api/auth/users/{id}/approve` (with role grant), `POST
  .../reject`, all Super-Admin-only, all writing an `audit_logs` row
  (login/logout deliberately do **not** write audit rows, per spec — they
  only update `last_login_at`/`last_logout_at`).
- **Frontend auth wiring** — `AuthContext`, `ProtectedRoute`, a real login
  page (Google button + optional dev-login panel), an OAuth callback page,
  a pending-approval screen (polls every 30s), and a not-authorized screen.
  Verified: `npx tsc --noEmit` is clean, `npm run build` succeeds, `npm run
  dev` serves the app.

### What was assumed (flag if wrong)

- **Role & Permission dashboard is Super-Admin-only**, not shared with
  Admin — letting Admin edit its own permission grants would be a
  privilege-escalation path. Revisit if Admin should have partial access.
- **Dev-login auto-approves new users** for local testing convenience only
  — it is unreachable outside `development` + `DEV_LOGIN_ENABLED=true`, so
  this doesn't weaken the real approval flow.

## Phase 1 + 2 verification (unchanged from before)

- **backend/app/models/** — SQLAlchemy 2.0 async models for all 24 tables
  from `schema-reference.pdf`, organized to mirror the schema doc's
  sections (identity/roles, teams/patents, legal parties, questionnaire/AI,
  templates/documents/jobs, files, collaboration/oversight).
- **backend/alembic/versions/** — the first migration, generated by real
  `alembic revision --autogenerate` against a live Postgres instance and
  verified to apply cleanly with `alembic upgrade head`. All 24 tables, every
  foreign key, and every unique constraint were confirmed present in the
  actual database afterward — including the two trickiest ones:
  - `applicants`: a **partial unique index** (`UNIQUE(patent_application_id)
    WHERE is_primary = true`) — tested with real inserts: a second
    non-primary applicant on the same patent succeeds (joint filing works),
    a second *primary* applicant on the same patent correctly fails.
  - `inventors`: `UNIQUE(patent_application_id, inventor_order)` — tested
    the same way; a duplicate order position on the same patent correctly
    fails.
- **backend/app/seed.py** — seeds the four roles (SUPER_ADMIN, ADMIN,
  PATENT_AGENT, INNOVATOR), a starter permission set (30 permissions: 5
  modules × 6 actions), grants all of them to SUPER_ADMIN, and creates one
  bootstrap Super Admin user. Verified idempotent — running it twice
  creates zero duplicates.
- **backend/** — FastAPI app, async SQLAlchemy engine, Loguru logging.
  Verified: imports cleanly, starts, and `/health` correctly reports
  `"degraded"` with no database reachable, and `"ok"`/`"connected"` once
  Postgres is actually up.
- **frontend/** — Vite + React + TypeScript + Tailwind, TanStack Query
  provider, React Router with placeholder routes. Verified: installs,
  type-checks with zero errors, dev server serves the app.
- **docker-compose.yml** — Postgres 17 only. Redis is deliberately not
  included yet — see the note in that file and in `backend/requirements.txt`.

## Run it

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values as below
```

Document generation (Phase 7) needs headless LibreOffice on the machine
running the backend for PDF conversion (DOCX generation alone doesn't need
it). Install it separately — it's not a pip package:

```bash
# Debian/Ubuntu
sudo apt-get install -y libreoffice
# confirm it's on PATH:
which soffice
```

If `soffice` isn't found or is at a different path, set
`LIBREOFFICE_BINARY` in `.env` accordingly. Generating DOCX-only still
works with no LibreOffice installed at all.

Start Postgres (either):

```bash
docker compose up -d          # from the repo root
```

Then apply the migration and seed the database:

```bash
alembic upgrade head
python -m app.seed            # creates roles, permissions, bootstrap Super Admin
uvicorn app.main:app --reload
```

Check it: `curl http://localhost:8000/health` — should return
`{"status":"ok","database":"connected",...}`.

The bootstrap Super Admin is created with the email
`SEED_SUPER_ADMIN_EMAIL` (defaults to `superadmin@example.com`).

#### Testing auth without Google OAuth credentials

Set these in `backend/.env` for local testing:

```
ENVIRONMENT=development
DEV_LOGIN_ENABLED=true
JWT_SECRET=<any long random string>
SESSION_SECRET=<a different long random string>
```

Then:

```bash
curl -X POST http://localhost:8000/api/auth/dev-login \
  -H "Content-Type: application/json" \
  -d '{"email":"superadmin@example.com","role_code":"SUPER_ADMIN"}'
```

This logs you in as the bootstrap Super Admin (claiming its placeholder
`google_id`) and returns a real JWT — use it as `Authorization: Bearer
<token>` against any endpoint, including `/api/rbac/*`. Dev-login with a
new email creates a fresh, auto-approved user with the given `role_code`.

**Never set `DEV_LOGIN_ENABLED=true` outside local development.**

#### Setting up real Google OAuth credentials

1. In [Google Cloud Console](https://console.cloud.google.com/), create an
   OAuth 2.0 Client ID (Web application).
2. Add `http://localhost:8000/api/auth/google/callback` as an authorized
   redirect URI (and your real backend URL once deployed).
3. Put the client ID/secret in `backend/.env` as `GOOGLE_CLIENT_ID` /
   `GOOGLE_CLIENT_SECRET`.
4. Visit `http://localhost:8000/api/auth/google/login` in a browser (not
   curl — it's a redirect flow) to sign in for real.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # set VITE_API_URL / VITE_DEV_LOGIN_ENABLED
npm run dev
```

Visit `http://localhost:5173` — real Google sign-in button, plus a Dev
Login panel if `VITE_DEV_LOGIN_ENABLED=true` (purely cosmetic — the
backend flag is the real gate). After signing in you'll land on your
role's dashboard; Super Admin additionally gets the Role & Permission
management UI at `/super-admin`.

## What's intentionally NOT here yet

- No files/comments/notifications-UI/calendar or reports — Phases 8–9.
  Teams, Patent Applications, Basic Information, Questionnaire, AI
  drafting, and document generation are all built and scoped/assignable.
- No Redis/Celery — deferred until a real trigger point makes the
  synchronous-request approach genuinely too slow (long-running AI
  refinement or a much heavier document pipeline than today's).
- No email sending (provider still TBD) — in-app notifications work
  independently per spec, so this isn't a blocker.
- No real Template merging or a Templates management UI — see the Phase 7
  section above.

See `README.md` for the full product overview, schema, and architecture, and
`Kiro_AI_Master_Prompt_and_Build_Guide.pdf` for the remaining phases (8:
files/comments/notifications/audit/calendar, 9: reports/dashboards, 10:
hardening/deployment).

