# Patent Platform Backend — Firebase Edition

This is a Firebase-based FastAPI backend. Its active runtime uses Firebase Authentication token verification, Cloud Firestore for application data, and Cloud Storage for uploaded files. It does not use Supabase, PostgreSQL, SQLAlchemy, Alembic, or Cloudflare R2.

> Migration status: this is a working Firebase-native backend foundation with core workflows and endpoints, not a verified feature-for-feature port of every original SQL backend workflow. The API contract and business rules must be validated against the product requirements before production use.

## 1. Requirements

- Python 3.11+ (Python 3.13 is supported by current dependencies)
- A Firebase project
- Firestore enabled
- Firebase Authentication enabled (enable Google and/or Email/Password in Firebase Console)
- Cloud Storage enabled if file upload/template endpoints are needed

## 2. Firebase setup

1. Open https://console.firebase.google.com/ and create/select your project.
2. In **Build → Firestore Database**, create a database. Pick the location carefully; it is difficult to change later.
3. In **Build → Authentication → Sign-in method**, enable the providers your client will use (for example Google).
4. In **Build → Storage**, enable a bucket if you need uploads/templates.
5. Open **Project settings → Service accounts → Generate new private key**.
6. Create `secrets/` in this backend folder and save the downloaded JSON as `secrets/firebase-service-account.json`.
7. Copy `.env.example` to `.env`, then set `FIREBASE_PROJECT_ID`, `FIREBASE_STORAGE_BUCKET` and `BOOTSTRAP_ADMIN_EMAIL`.

The service-account JSON and `.env` contain sensitive values. Do not commit or send them to anyone. The provided `.gitignore` excludes them.

## 3. Install and run on Windows PowerShell

Run these commands from this folder:

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and add your Firebase settings before authenticated API testing.
python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs and http://127.0.0.1:8000/health.

The API process can start before Firebase credentials exist; `/health` will return HTTP 503 until Firebase is configured and reachable. Authenticated endpoints require a **Firebase ID token** in `Authorization: Bearer <ID_TOKEN>`. Login is performed by Firebase Authentication on the client; the client sends its ID token to this API. The backend `/api/auth/sync` endpoint syncs optional profile fields.

## 4. First administrator

Set `BOOTSTRAP_ADMIN_EMAIL` to an email you control before first sign-in. When a Firebase-authenticated user with that email calls the API, their profile is assigned `SUPER_ADMIN` and approved status. Protect this email and remove/change the bootstrap setting after initial setup according to your deployment policy. Do not rely on client-provided role values; role assignment is admin-protected on the server.

## 5. Main endpoints

- `GET /health`
- `GET /api/auth/me`, `POST /api/auth/sync`, `POST /api/auth/logout`
- `GET /api/auth/pending-users`, `POST /api/auth/users/{uid}/approve`, `POST /api/auth/users/{uid}/reject`
- `GET/POST /api/teams`, `GET/PATCH /api/teams/{id}`, member add/remove
- `GET/POST /api/patents`, `GET/PATCH /api/patents/{id}`, submit and agent assignment workflow
- Patent subresources for applicants, inventors, comments, calendar events, questionnaire and versions
- Draft generation/version listing (stub by default; optional Gemini configuration)
- File upload/download/delete through Firebase Storage
- Notifications, calendar, templates, basic dashboard/reports and role assignment

Firestore is NoSQL. It does not support SQL joins or Alembic migrations; documents are stored in collections and linked with string IDs. Review and expand the collection schema and access rules as workflows evolve.

## 6. GitHub safety and push

From your existing project repository root (the folder containing `.git`), copy this backend folder into the repository as `backend_firebase/`. Do not initialize a second Git repository inside it. Then:

```powershell
git status
git add backend_firebase
git commit -m "Add Firebase backend migration"
git push origin main
```

Before committing, verify that `.env`, `secrets/firebase-service-account.json`, and any other credentials are not staged:

```powershell
git status --short
```

If a real service-account key or `.env` was committed previously, deleting it in a later commit is not enough; revoke/rotate the exposed credential.

## 7. Testing checklist

- `GET /health` returns `200` with Firebase connected.
- Firebase Auth returns a valid ID token for a signed-in user.
- `/api/auth/me` returns the matching profile with a Bearer ID token.
- New users are pending until approved, except the configured bootstrap administrator.
- Verify owner/role access on every endpoint with separate Innovator, Patent Agent, Admin and Super Admin accounts.
- Upload/download/delete a test file after enabling Storage.
- Test all patent assignment, questionnaire, document generation, report, and template scenarios before production.

## Security notes

- Firebase Admin SDK runs with privileged server credentials. Firestore Security Rules do not replace backend authorization checks for Admin SDK calls.
- Use HTTPS in production, restrict CORS and allowed hosts, keep service-account keys outside source control, and configure backups/retention.
- Generated patent text is a draft only and is not legal advice.
