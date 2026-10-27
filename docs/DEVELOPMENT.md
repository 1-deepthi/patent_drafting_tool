# Development guide

## 1. Daily workflow

```powershell
# Terminal 1 — backend (from backend/, venv active):
python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend (from frontend/):
npm run dev
```

- Backend docs: http://127.0.0.1:8000/docs · health: http://127.0.0.1:8000/health
- Frontend: http://localhost:5173 (`VITE_API_URL` must point at the backend)
- Firebase is external. Without credentials the backend still boots; `/health`
  reports `503 degraded` and authenticated calls fail.

## 2. Project conventions

**Backend (`backend/app/`):**

- Routers: `api/auth.py` (identity/profile/approval) and `api/resources.py`
  (everything else). There are no other routers.
- Core: `core/config.py` (settings), `core/firebase.py` (lazy Admin SDK init),
  `core/security.py` (`current_user`, `active_user`, `require_roles`,
  `is_admin`, `is_super_admin`, `ensure_permission`).
- Services: `repository.py` (thin Firestore CRUD/query helpers),
  `projections.py` (REST shapes + visibility), `rbac.py` (role/permission
  catalog and overrides), `storage.py` (Cloud Storage), `drafting.py`
  (stub/Gemini text), `documents.py` (DOCX/PDF).
- Guards: `active_user` → `ensure_permission("<CODE>")` and/or
  `require_roles(*codes)` / `is_admin()`; visibility via
  `services/projections.py` (`patent_visible`, `require_patent`).
- Firestore stores lowercase internal state (`account_status`, `role_codes`);
  never expose raw documents — serialise through `projections.py`.
- Never trust client-supplied roles or IDs. Firestore document IDs are opaque
  strings; RBAC catalog IDs are the only numbers.

**Frontend (`frontend/src/`):**

- `App.tsx` owns the route map; `ProtectedRoute` owns gating; `AuthContext`
  owns Firebase session state and the 30-minute idle sign-out.
- All HTTP goes through `lib/api.ts` (`apiFetch`, `apiUpload`, `apiDownload`);
  `setTokenProvider` is registered by `AuthContext` so every request gets a
  fresh Firebase ID token. Never call `fetch` with a manually cached token.
- `lib/firebase.ts` initialises the Web SDK lazily and throws
  `FirebaseConfigError` when `VITE_FIREBASE_*` values are missing.
- Types + constants live in `lib/types.ts` (`STATUS_COLOR`, `ROLE_HOME`,
  `SECTION_TYPES`, `NOTIFICATION_TEXT`, `CALENDAR_EVENT_TYPES`). Entity IDs
  are strings; only RBAC role/permission IDs are numeric.
- Layout via `DashboardShell`; status via `StatusBadge`; loading/empty states
  via `LoadingState` / `EmptyState` (centred, `role="status"`).
- TypeScript `strict` + `noUnusedLocals`/`noUnusedParameters`: keep imports clean.

## 3. Scripts reference

| Location | Command | Purpose |
|---|---|---|
| `backend/` | `python -m uvicorn app.main:app --reload --port 8000` | Dev server |
| `backend/` | `python -m compileall app` | Syntax check (CI gate) |
| `backend/` | `python -m pytest -q` | Offline test suite |
| `backend/` | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000` | Prod serve (Docker CMD; Linux only) |
| `frontend/` | `npm run dev` | Dev server `:5173` |
| `frontend/` | `npm run lint` | `eslint .` (advisory until configured) |
| `frontend/` | `npm run build` | `tsc -b && vite build` |
| `frontend/` | `npm run preview` | Preview `dist/` |
| Root | `docker compose up --build` | Backend + frontend images (Firebase external) |

## 4. Environment handling

- Backend: copy `backend/.env.example` → `backend/.env`; service-account JSON
  → `backend/secrets/firebase-service-account.json`. Both git-ignored.
  `config.py` uses `extra='ignore'`, so stale variables do not crash startup —
  but do not add new ones without updating `.env.example` and the docs.
- Firebase rules are committed: `firestore.rules` and `storage.rules` deny all
  direct client access. Deploy them with
  `firebase deploy --only firestore:rules,storage`. Do not weaken a rule to
  unblock a local test — the browser only uses Firebase Auth and must go
  through the API. The Firebase CLI cache (`.firebase/`), its debug logs, and
  admin-SDK key files are git-ignored.
- Frontend: copy `frontend/.env.example` → `frontend/.env`. `VITE_*` bake at
  build time — changing them requires restarting `npm run dev` or rebuilding
  (`npm run build` / Docker build arg).
- Never log tokens, service-account JSON, or `GEMINI_API_KEY`. Redact before
  pasting logs into issues.

## 5. Tests

- `backend/tests/conftest.py` forces empty Firebase credentials **before**
  importing the app, so the lifespan records "Firebase not configured"
  instead of reaching the network.
- `backend/tests/test_smoke.py` asserts:
  - the app boots and `/health` reports degraded without credentials;
  - every path the React client calls is mounted (`CONTRACT_PATHS`);
  - the RBAC catalog is internally consistent;
  - stub drafting always carries the not-legal-advice warning;
  - DOCX assembly produces a non-empty document.
- Live Firestore/Auth/Storage and LibreOffice PDF conversion are **not** in
  pytest. Verify them with the manual checklist in `backend/README.md` §7.
- Frontend: no unit runner yet. Verify with `npm run build` (type-check) +
  manual walkthroughs per role. Adding `vitest` is a welcome `help wanted`
  contribution (document it here in the same PR).

## 6. Common errors

| Error | Cause | Fix |
|---|---|---|
| `firebase: not_configured_or_unreachable` (`503`) | Bad project ID / service-account path / no network | Recheck `FIREBASE_*`, filename under `secrets/`, emulator vars unset |
| `401 Invalid token` | Expired or non-Firebase token | Re-login; confirm the Bearer header and that `AuthContext` registered the token provider |
| `403 awaiting approval` | Pending account | Admin approval via `/super-admin` |
| `422 Unprocessable Entity` | Missing required body field | Compare against `API_OVERVIEW.md` payload |
| `CORS blocked` | Origin not in `CORS_ORIGINS` | Add the exact origin; restart backend |
| Login page shows a configuration error | `VITE_FIREBASE_*` empty | Fill `frontend/.env`, restart `npm run dev` |
| `auth/unauthorized-domain` | Frontend origin not registered | Firebase console → Authentication → Authorized domains |
| `tsc` unused-var errors | `noUnusedLocals` | Delete unused imports/params |
| LibreOffice missing locally | DOCX→PDF shells out | Use the Docker image (has LibreOffice) or skip PDF locally |

## 7. Debugging tips

- Backend: run uvicorn with `--reload`, read non-prod 500 messages
  (`Type: msg`), and inspect `/health` for the Firebase error detail.
- Frontend: open DevTools → Network, confirm requests go to `VITE_API_URL`
  and carry an `Authorization` header. There is no token in `localStorage` —
  Firebase owns the session.
- Firestore: use Firebase Console → Firestore Data viewer to confirm document
  shapes (`role_codes`, `account_status`, `patent_application_id` links).
- Storage: confirm the bucket name matches `FIREBASE_STORAGE_BUCKET`; check
  blob prefixes `patents/{id}/files/`, `templates/{type}/v{n}.docx`, and the
  generated-document prefix used by `services/documents.py`.

## 8. Performance notes

- Firestore list helpers cap at 100–500 docs. For large tenants, add query
  filters or pagination rather than loading everything and filtering in Python.
- `recharts` + `FullCalendar` are the heaviest frontend deps; pages are route-
  split, so keep them out of the login bundle.
- The backend Docker image is large because of LibreOffice — expected. Removing
  it also removes PDF generation.
- Document generation runs in-process and spawns LibreOffice; the deployment
  assumes one backend replica (ADR-003).
