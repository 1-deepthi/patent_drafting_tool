# Deployment Guide

Production deployment for **patent_drafting_tool** on the Firebase-only runtime
(ADR-005). The shape is:

```text
Firebase Authentication + Cloud Firestore + Cloud Storage   (managed, external)
                     ^                        ^
                     |                        |
        one backend container        one static/nginx frontend
        (FastAPI + Admin SDK)        (Vite bundle, nginx SPA fallback)
```

There is no database container, no migration step, and no object-storage
vendor. The backend is stateless: every request verifies a Firebase ID token
and reads/writes Firestore, so redeploys do not move data.

The steps below generalize to any Dockerfile-based PaaS (Koyeb, Render,
Fly.io, Railway, Cloud Run, ECS) and to a plain VM. Swap the dashboard
sections for your platform's equivalent.

> This guide has not been executed against a live production Firebase project
> from this repository's CI. Treat the checklist in §6 as the release gate.
> Generated patent text remains a draft, never legal advice.

## 1. Create the production Firebase project

1. Create a Firebase project at https://console.firebase.google.com/.
2. **Build → Firestore Database** → create the database in the region closest
   to your users. The location cannot be changed later.
3. **Build → Authentication → Sign-in method** → enable **Google**. Add the
   production frontend domain under **Authorized domains**.
4. **Build → Storage** → enable a bucket if uploads, templates, or generated
   documents are needed. Note the bucket name.
5. **Project settings → Your apps → Web app** → register the production web
   app. Copy the six `VITE_FIREBASE_*` values for the frontend build.
6. **Project settings → Service accounts → Generate new private key** → store
   the JSON in your platform's secret manager. Never commit it.

Use separate Firebase projects for staging and production. Auth users,
Firestore data, and Storage buckets are per project.

## 2. Configure the backend

The backend reads `backend/.env` locally and environment variables in
production (`pydantic-settings`; see `backend/app/core/config.py`). Set:

| Variable | Production value |
|---|---|
| `ENVIRONMENT` | `production` |
| `FIREBASE_PROJECT_ID` | The production project ID |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Path to the mounted service-account JSON (for example `/run/secrets/firebase-service-account.json`) |
| `FIREBASE_STORAGE_BUCKET` | The production bucket |
| `FIREBASE_EMULATOR_HOST` | Empty (never set in production) |
| `BOOTSTRAP_ADMIN_EMAIL` | An address you control, for the first login |
| `CORS_ORIGINS` | The exact frontend origin, e.g. `https://app.example.com` |
| `ALLOWED_HOSTS` | The exact backend host, e.g. `api.example.com` |
| `MAX_UPLOAD_SIZE_BYTES` | Keep the default (10 MiB) or lower |
| `BLOCKED_UPLOAD_EXTENSIONS` | Keep the default deny-list |
| `AI_PROVIDER` | `stub` unless you intend to pay for Gemini |
| `GEMINI_API_KEY` | Only when `AI_PROVIDER=gemini`; store as a secret |

Rules:

- `CORS_ORIGINS` must not contain `*` or a `localhost` origin in production.
- `ALLOWED_HOSTS` must contain the real backend host; the default `*` is a
  development convenience, not a production setting.
- The service-account JSON is mounted read-only or injected by the platform's
  secret manager. Do not bake it into the image.
- Rotate `GEMINI_API_KEY` and the service-account key if either is exposed;
  deleting a later commit is not enough.

## 3. Deploy the backend

1. Point the platform at this repository, root directory `backend/`, build
   method Dockerfile (`backend/Dockerfile`).
2. Expose port `8000`.
3. Set the health check to `GET /health`. It returns `200` only when the
   Firestore probe succeeds; `503` means the credentials, project ID, or
   network are wrong.
4. Mount the service-account JSON at the path in
   `FIREBASE_SERVICE_ACCOUNT_PATH`.
5. Deploy. There is no entrypoint and no migration step: Gunicorn starts
   two Uvicorn workers and serves immediately. Boot logs should show the
   workers binding `0.0.0.0:8000`; a `503` health check with a Firebase
   message means configuration, not a stuck migration.

The image installs LibreOffice for DOCX→PDF conversion. That is the main
size cost and the reason the worker count is two: each worker can spawn a
LibreOffice subprocess, and the deployment assumes a single container
(ADR-003).

## 4. Deploy the frontend

The frontend is a static Vite bundle. `VITE_*` values are fixed at build
time; runtime environment variables cannot change them.

**A. Static hosting** (Cloudflare Pages, Netlify, Vercel, Firebase Hosting,
S3 + CDN):

```powershell
cd frontend
npm ci
$env:VITE_API_URL = "https://api.example.com"
$env:VITE_FIREBASE_API_KEY = "..."
# ... the other five VITE_FIREBASE_* values ...
npm run build
# upload frontend/dist/ with a catch-all rewrite to index.html
```

**B. Container** (`frontend/Dockerfile`, nginx with SPA fallback):

```powershell
docker build `
  --build-arg VITE_API_URL=https://api.example.com `
  --build-arg VITE_FIREBASE_API_KEY=... `
  --build-arg VITE_FIREBASE_AUTH_DOMAIN=my-project.firebaseapp.com `
  --build-arg VITE_FIREBASE_PROJECT_ID=my-project `
  --build-arg VITE_FIREBASE_STORAGE_BUCKET=my-project.appspot.com `
  --build-arg VITE_FIREBASE_MESSAGING_SENDER_ID=... `
  --build-arg VITE_FIREBASE_APP_ID=... `
  -t patent-frontend ./frontend
docker run -p 8080:80 patent-frontend
```

Either way:

- Add the production frontend domain to Firebase Authentication →
  **Authorized domains**, otherwise Google sign-in fails with
  `auth/unauthorized-domain`.
- Keep the SPA rewrite (`/*` → `index.html`) so deep links such as
  `/agent/patents/<id>/draft` work on refresh.
- Serve over HTTPS. Firebase Auth requires a secure context outside
  `localhost`.

## 5. First login and role bootstrap

1. Open the deployed frontend and sign in with `BOOTSTRAP_ADMIN_EMAIL`.
2. The first `/api/auth/me` call creates `users/{uid}` with
   `role_codes = ["SUPER_ADMIN"]` and `account_status = approved`
   (`app/core/security.py`).
3. Approve subsequent users from `/super-admin` → Pending Approvals.
4. After the first login, remove or change `BOOTSTRAP_ADMIN_EMAIL` according
   to your policy. It is a bootstrap escape hatch, not a permanent role grant.

## 6. Verify the deployment

Run this checklist against the real project before calling the deployment
done:

1. `GET https://<backend-host>/health` → `200` with Firestore connected.
2. Load the frontend, open DevTools → Network, and confirm `/api/auth/me`
   returns `{user, permissions}` with an `Authorization: Bearer …` header.
3. Sign in with a non-bootstrap Google account → lands on
   `/pending-approval`; approve it from the Super Admin dashboard.
4. Innovator path: create team → create patent → add applicant/inventor →
   complete questionnaire → submit.
5. Admin path: assign the patent to an approved `PATENT_AGENT`; try
   auto-assign as well.
6. Agent path: accept → generate a draft section → generate DOCX → download
   it → generate PDF (confirms LibreOffice in the image) → comment.
7. Upload a file, download it, delete it; confirm the Storage objects appear
   under the expected prefixes.
8. Upload/activate a `.docx` template, then generate a document from it.
9. Export a report CSV; toggle a report permission and confirm the export is
   denied for the affected role.
10. Check the backend logs for unhandled `500`s and confirm the production
    error response stays terse.

## 7. Scale and availability

This release assumes **one backend replica** (ADR-003). Document generation
runs inside the request and may spawn LibreOffice; there is no job queue and
no shared rate limiter. Before adding replicas:

- move document generation to a worker/job queue with retries and a shared
  status store, and
- put rate limiting at the platform edge (PaaS/WAF/Firebase quotas) or back
  it with a shared store.

Ordinary read traffic can be scaled at the frontend/CDN layer without
touching the backend.

## 8. Backups and retention

- Firestore: enable scheduled backups (or export to a Cloud Storage bucket)
  and test a restore. Firestore has no `pg_dump`.
- Storage: enable object versioning or a lifecycle policy appropriate to
  your retention obligations.
- Firebase Authentication: user records are managed by Firebase; document
  the export/recovery process you rely on.
- Generated drafts and documents are drafting aids. Retain them according to
  your firm's records policy, not indefinitely by default.

## 9. Rollback

- Backend: redeploy the previous image tag. There is no schema migration to
  reverse; Firestore documents are forward/backward compatible as long as
  field names do not change.
- Frontend: redeploy the previous static build. `VITE_*` values are part of
  that build, so a rollback also restores the previous Firebase project
  configuration.
- Data: Firestore writes are not transactional across collections. If a
  release changes document shapes, ship a read-compatible projection first
  (the pattern used by `app/services/projections.py`) and remove the old
  shape in a later release.

## What this guide deliberately does not cover

- **No automated deploy job.** CI builds and tests; wiring a platform deploy
  needs an account-specific token and is left to the maintainer.
- **No CDN configuration.** nginx/static-host caching is the extent of it;
  add a CDN when traffic justifies it.
- **No secrets-manager integration.** Use your platform's secret store; the
  repository only documents which values are secret.
- **No multi-region Firestore.** Choose the region in §1; changing it later
  is a migration project.
