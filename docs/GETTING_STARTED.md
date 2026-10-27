# Getting started

Step-by-step first run for **patent_drafting_tool**, from zero to a logged-in
admin. The stack is Firebase-only: Authentication, Firestore, and Storage are
managed services; the repository contains the FastAPI backend and the React
frontend.

---

## 1. What you need

- Python 3.11+ (3.13 recommended), Node 20.x, Git, and (optionally) Docker + Compose.
- A Firebase project with **Firestore**, **Authentication** (Google), and — for uploads — **Cloud Storage**.
- Windows PowerShell commands are shown; macOS/Linux users translate `Copy-Item` → `cp` and venv activation to `source venv/bin/activate`.

## 2. Clone

```powershell
git clone https://github.com/auraflaa/patent_drafting_tool.git
cd patent_drafting_tool
```

## 3. Create the Firebase project

Follow `backend/README.md` §2 (summary here — the backend README is authoritative):

1. Go to https://console.firebase.google.com/ → create or select a project. Note the **Project ID**.
2. **Build → Firestore Database** → Create database. Choose the region carefully (hard to change later).
3. **Build → Authentication → Sign-in method** → enable **Google**. Under **Authorized domains**, `localhost` is present by default; add your production domain later.
4. **Build → Storage** → enable a bucket if uploads/templates are needed. Note the bucket name.
5. **Project settings → Service accounts → Generate new private key** → save the JSON as `backend/secrets/firebase-service-account.json` (create the `secrets/` folder; it is git-ignored).
6. **Project settings → Your apps → Web app** → register an app and copy the six `VITE_FIREBASE_*` values.
7. Install the Firebase CLI (`npm i -g firebase-tools`), run `firebase login` and `firebase use --add` from the repository root, then deploy the checked-in rules: `firebase deploy --only firestore:rules,storage`. They deny all direct browser access because only the backend Admin SDK reads and writes Firestore and Storage.
8. Decide your bootstrap admin email — an address you control. Never use a shared address.

Firestore is the only system of record (ADR-005). The Realtime Database is not
used, even if the Web app config displays a `databaseURL`.

## 4. Configure the backend

```powershell
cd backend
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env`:

```ini
FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_SERVICE_ACCOUNT_PATH=secrets/firebase-service-account.json
FIREBASE_STORAGE_BUCKET=your-firebase-storage-bucket
BOOTSTRAP_ADMIN_EMAIL=you@example.com
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
ALLOWED_HOSTS=localhost,127.0.0.1
```

Start it:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Verify:

- http://127.0.0.1:8000/docs — Swagger UI
- http://127.0.0.1:8000/health — `{"status":"ok","firebase":"connected",...}` once credentials are valid; `503 degraded` before that is **expected**.

## 5. Configure the frontend

New terminal:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
```

Edit `frontend/.env`:

```ini
VITE_API_URL=http://localhost:8000
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project
VITE_FIREBASE_STORAGE_BUCKET=your-project.firebasestorage.app
VITE_FIREBASE_MESSAGING_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
```

These values are public identifiers, not secrets. If they are missing the
app still builds, but the login screen shows a configuration error instead of
a Google button. `VITE_*` values are baked at dev-server start/build time, so
restart `npm run dev` after editing.

Start it:

```powershell
npm run dev
```

Open http://localhost:5173.

## 6. First admin login

1. Confirm `BOOTSTRAP_ADMIN_EMAIL` in `backend/.env` is your address.
2. Sign in on the frontend with that address via Google.
3. The backend auto-creates your `users/{uid}` profile as `SUPER_ADMIN` + approved (see `app/core/security.py` bootstrap logic).
4. Go to `/super-admin` → **Pending Approvals** to approve subsequent users.
5. Remove or change `BOOTSTRAP_ADMIN_EMAIL` after initial setup per your deployment policy.

## 7. Happy-path smoke test (10 minutes)

As **Innovator**:

1. `/innovator` → create a team → create a patent in it.
2. Open the patent → **Basic Info** tab → add an applicant + inventor.
3. **Questionnaire** tab → fill required fields → save → **Submit** the patent.

As **Admin/Super Admin**:

4. `/super-admin` or `/admin/patents` → open the submitted patent → **Assign** (or **Auto-assign**) an approved `PATENT_AGENT`.

As **Patent Agent**:

5. `/agent` → accept the assignment.
6. `/agent/patents/:id/draft` → **Generate** a `Summary` section → confirm a version appears.
7. Generate a DOCX document → confirm download works. PDF generation requires LibreOffice; use the Docker image if it is not installed locally.
8. Upload a supporting file, download it, then delete it.

As **Admin**:

9. `/admin` → upload a `.docx` template → activate it.
10. `/innovator/reports` or `/admin/reports` → confirm dashboard counts move and a CSV export downloads.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `/health` → `503` | Service-account path wrong, project ID mismatch, or no network to Firebase. Check `FIREBASE_*` values and `secrets/` filename. |
| `401` on API calls | No `Authorization: Bearer <Firebase ID token>` header. Re-login; inspect `src/lib/api.ts` token flow. |
| Login page shows a configuration error | One or more `VITE_FIREBASE_*` values are empty. Fill `frontend/.env` and restart the dev server. |
| `auth/unauthorized-domain` from Google | Add the frontend origin under Firebase Authentication → Authorized domains. |
| `403 awaiting approval` | Account is pending. Approve it via the Super Admin dashboard. |
| CORS errors in browser console | `CORS_ORIGINS` must include the exact frontend origin (`http://localhost:5173`). |
| `TrustedHost` 400s | `ALLOWED_HOSTS` must include `localhost,127.0.0.1`. |
| Uploads fail | Bucket unset, `MAX_UPLOAD_SIZE_BYTES` exceeded, or a blocked extension. Check backend logs (non-prod includes the reason). |
| PDF generation fails locally | LibreOffice (`soffice`) is not installed; DOCX still works. Use `docs/DOCKER.md` for PDF. |
| Draft returns placeholder | Expected without `AI_PROVIDER=gemini` + `GEMINI_API_KEY`. Set both to enable real generation. |

Still stuck? See [`SUPPORT.md`](../SUPPORT.md) and [`DEVELOPMENT.md`](./DEVELOPMENT.md).
