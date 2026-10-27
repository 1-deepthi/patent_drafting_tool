# Backend — Firebase edition

FastAPI backend for patent_drafting_tool. Firebase Authentication verifies
identity, Cloud Firestore is the only system of record, and Cloud Storage
holds blobs. There is no Supabase, PostgreSQL, SQLAlchemy, Alembic, or
object-storage vendor in this tree (ADR-005).

The only mounted routers are `app/api/auth.py` and `app/api/resources.py`.
Everything else lives in `app/core/` (config, Firebase init, guards) and
`app/services/` (repository, projections, RBAC, storage, drafting, documents).

## 1. Requirements

- Python 3.11+ (3.13 is what the Docker image uses)
- A Firebase project with:
  - Cloud Firestore enabled
  - Firebase Authentication enabled (Google provider for the shipped UI)
  - Cloud Storage enabled if uploads/templates/generated documents are needed

## 2. Firebase setup

1. Open https://console.firebase.google.com/ and create/select your project.
2. **Build → Firestore Database** → create a database. Pick the location
   carefully; it is difficult to change later.
3. **Build → Authentication → Sign-in method** → enable **Google**. Add
   `localhost` and your production domain under **Authorized domains**.
4. **Build → Storage** → enable a bucket if you need uploads/templates.
5. **Project settings → Your apps** → register a Web app and copy the six
   `VITE_FIREBASE_*` values for the frontend.
6. **Project settings → Service accounts → Generate new private key** → save
   the downloaded JSON as `secrets/firebase-service-account.json` (create the
   folder; it is git-ignored).
7. From the repository root, deploy the client rules with
   `firebase deploy --only firestore:rules,storage` (after
   `firebase login` and `firebase use --add`). The browser never talks to
   Firestore or Storage directly, so `firestore.rules` and `storage.rules`
   deny every client request while the Admin SDK keeps full access. This
   project does not use the Realtime Database; Firestore is the only system
   of record (ADR-005).
8. Copy `.env.example` to `.env`, then set `FIREBASE_PROJECT_ID`,
   `FIREBASE_STORAGE_BUCKET`, and `BOOTSTRAP_ADMIN_EMAIL`.

The service-account JSON and `.env` contain sensitive values. Do not commit
or share them; `.gitignore` excludes both.

## 3. Install and run (Windows PowerShell)

Run these commands from `backend/`:

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env with your Firebase settings before authenticated API testing.
python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs and http://127.0.0.1:8000/health.

The process starts before Firebase credentials exist; `/health` returns
`503` until Firebase is configured and reachable. Authenticated endpoints
require a **Firebase ID token** in `Authorization: Bearer <ID_TOKEN>`. The
browser obtains that token from the Firebase JS SDK; the API verifies it and
never mints tokens. `POST /api/auth/sync` merges optional profile fields.

## 4. First administrator

Set `BOOTSTRAP_ADMIN_EMAIL` before the first sign-in. The first authenticated
call from that email creates `users/{uid}` with `role_codes = ["SUPER_ADMIN"]`
and `account_status = approved`. Remove or change the setting after initial
setup according to your deployment policy. Never trust client-supplied role
values; role assignment is Super Admin-only on the server.

## 5. Main endpoints

- `GET /health` — Firestore probe (`200 ok` / `503 degraded`)
- `GET /api/auth/me`, `POST /api/auth/sync`, `POST /api/auth/logout`
- `GET /api/auth/pending-users`, `POST /api/auth/users/{uid}/approve|reject`
- `GET/POST /api/teams`, `GET /api/teams/{id}`, member add/remove
- `GET/POST /api/patents`, `GET /api/patents/{id}`, submit and agent
  assignment workflow (assign / auto-assign / reassign / accept / reject)
- Patent subresources: applicants, inventors, comments, calendar events,
  questionnaire and versions, draft generation/version listing
- Files and documents: upload, generate, retry, version list, streamed
  download, delete
- Notifications, calendar, templates, dashboards/reports, RBAC and report
  permissions

The full catalog with permission requirements is in
[`../docs/API_OVERVIEW.md`](../docs/API_OVERVIEW.md).

### Runtime limits

`GET /api/config/capabilities` is public and returns the deployment profile:
`deployment_target`, `max_upload_size_bytes`, `max_request_body_bytes`, and
`pdf_generation_enabled`. The React client reads it once per page load, checks
file sizes before uploading, and hides PDF generation when it is unavailable.

| Variable | Default | Effect |
|---|---|---|
| `DEPLOYMENT_TARGET` | `self_hosted` | `vercel` clamps uploads to 4 MiB and whole requests to 4.5 MB |
| `MAX_UPLOAD_SIZE_BYTES` | `0` | `0` = profile default (10 MiB self-hosted, 4 MiB Vercel); explicit values are still clamped on Vercel |
| `PDF_CONVERSION_ENABLED` | unset | `true`/`false`; unset = on except on Vercel, and the API reports PDF off if LibreOffice is missing |

Requests over the body limit are rejected with `413` before routing, and
multipart uploads are also counted while streaming, so a missing
`Content-Length` does not bypass the cap. Downloads stream from Cloud Storage
instead of buffering the whole object in memory.

Firestore is NoSQL: there are no joins and no migrations. Documents are
stored in collections and linked by string IDs. The collection map is in
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) §4.

## 6. Tests and checks

```powershell
# From backend/ with the venv active
python -m compileall app
python -m pytest -q
pyflakes app        # optional, if installed
```

The pytest suite is **offline**: `tests/conftest.py` forces empty Firebase
configuration, so the tests assert boot, the mounted frontend contract, and
the pure-Python services (RBAC catalog, stub drafts, DOCX rendering). No
credentials, network, or emulator are required.

Live behaviour is **not** covered by pytest. Use the checklist in §7 against
a real Firebase project before shipping.

## 7. Manual verification checklist

- `GET /health` returns `200` with Firebase connected.
- Firebase Auth returns a valid ID token for a signed-in user.
- `/api/auth/me` returns the matching profile with a Bearer ID token.
- New users are pending until approved, except the configured bootstrap admin.
- Verify owner/role access with separate Innovator, Patent Agent, Admin, and
  Super Admin accounts.
- Upload/download/delete a test file after enabling Storage.
- Generate DOCX and PDF documents; confirm downloads and the draft-only
  warning.
- Upload/activate a `.docx` template and generate from it.
- Exercise assignment, questionnaire, reports, and template scenarios.
- Confirm `PATCH`/`DELETE` on another user's resource returns `403`/`404`,
  not silent success.

## 8. Security notes

- The Firebase Admin SDK runs with privileged server credentials. Firestore
  Security Rules do **not** replace backend authorization for Admin SDK
  calls; all checks live in `app/core/security.py` and
  `app/services/projections.py`.
- Use HTTPS in production, restrict CORS and allowed hosts, keep
  service-account keys outside source control, and configure Firestore
  backups/retention.
- Uploads are validated for non-empty content, size, and blocked extensions.
  Do not weaken that validation for convenience.
- Generated patent text is a draft only and is not legal advice.
