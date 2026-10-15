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

## 2. Project conventions

**Backend (`backend/app/`):**

- Active code: `api/auth.py`, `api/resources.py`, `core/config.py`, `core/firebase.py`, `core/security.py`, `services/repository.py`, `services/ai/`, `main.py`.
- Reference-only (do not extend): `models/` (SQLAlchemy), `alembic/`, the other 13 `api/*.py` routers, SQL `services/*`, legacy `core/{database,oauth,startup_checks,rate_limit,middleware,logging_config}.py`.
- Guards: `active_user` → `require_roles(*codes)` → `is_admin()`; visibility via `repository._visible` / `_owned_get`.
- Return user docs via `clean()` (strip `_`-prefixed internals); raise `404` from `patch_doc`/`delete_doc` helpers; assignment flows validate agent role + approval.

**Frontend (`frontend/src/`):**

- `App.tsx` owns the route map; `ProtectedRoute` owns gating; `AuthContext` owns session state (`loading | unauthenticated | pending | approved`).
- All HTTP goes through `lib/api.ts` (`apiFetch`, `apiUpload`, `apiDownload`) — never raw `fetch` with manual tokens.
- Types + constants live in `lib/types.ts` (`STATUS_COLOR`, `ROLE_HOME`, `SECTION_TYPES`, `NOTIFICATION_TEXT`, `CALENDAR_EVENT_TYPES`).
- Layout via `DashboardShell`; status via `StatusBadge`; panels (`CollaborationPanel`, `DocumentGenerationPanel`, `TemplatesPanel`) are feature-scoped.
- TypeScript `strict` + `noUnusedLocals`/`noUnusedParameters`: keep imports clean.

## 3. Scripts reference

| Location | Command | Purpose |
|---|---|---|
| `backend/` | `python -m uvicorn app.main:app --reload --port 8000` | Dev server |
| `backend/` | `python -m compileall app` | Syntax check (CI gate) |
| `backend/` | `python -m pytest -q` | Test suite (legacy SQL targets — see §5) |
| `backend/` | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000` | Prod serve (Docker CMD) |
| `frontend/` | `npm run dev` | Dev server `:5173` |
| `frontend/` | `npm run lint` | `eslint .` |
| `frontend/` | `npm run build` | `tsc -b && vite build` |
| `frontend/` | `npm run preview` | Preview `dist/` |
| Root | `docker compose up --build` | Postgres + backend full-stack |

## 4. Environment handling

- Backend: copy `backend/.env.example` → `backend/.env`; secrets JSON → `backend/secrets/firebase-service-account.json`. Both git-ignored. `config.py` uses `extra='ignore'` so unknown vars don't crash.
- Frontend: copy `frontend/.env.example` → `frontend/.env`. `VITE_*` bake at build time — changing them requires rebuilding (`npm run build` or Docker build arg).
- Never log tokens, service-account JSON, or `GEMINI_API_KEY`. Redact before pasting logs into issues.

## 5. Tests

- `backend/pytest.ini`: `asyncio_mode = auto`, session-scoped loop.
- `backend/tests/`: `conftest.py` (env forcing, fixtures, `make_user` via legacy `dev-login`), `helpers.py` (builders), `test_*.py` per domain.
- Current reality: tests target the **legacy SQL API** and expect Postgres + legacy mounts. On a Firebase-only checkout they fail for environment reasons — report as migration debt, don't delete.
- Frontend: no unit runner yet. Verify with `npm run build` (type-check) + manual walkthroughs per role. Adding `vitest` is a welcome `help wanted` contribution (document in the same PR).

## 6. Common errors

| Error | Cause | Fix |
|---|---|---|
| `firebase: not_configured_or_unreachable` (`503`) | Bad project ID / service-account path / no network | Recheck `FIREBASE_*`, filename under `secrets/`, emulator vars unset |
| `401 Invalid token` | Expired or non-Firebase token | Re-login; confirm Bearer header |
| `403 awaiting approval` | `pending` account | Admin approval via `/super-admin` |
| `422 Unprocessable Entity` | Missing required body field | Compare against `API_OVERVIEW.md` payload |
| `CORS blocked` | Origin not in `CORS_ORIGINS` | Add exact origin; restart backend |
| `tsc` unused-var errors | `noUnusedLocals` | Delete unused imports/params |
| `eslint` missing config | No custom config in repo | Default `eslint .` (CI-tolerant); propose shared config as improvement |
| LibreOffice missing locally | DOCX→PDF shells out | Use Docker image (has LibreOffice) or skip PDF locally |

## 7. Debugging tips

- Backend: run uvicorn with `--reload`, read non-prod 500 messages (`Type: msg`), check `/health` detail field for Firebase errors.
- Frontend: open DevTools Network tab, confirm `VITE_API_URL` in built bundle (search `dist/assets/*.js`), check `localStorage: patent_platform_token` presence.
- Firestore: use Firebase Console → Firestore Data viewer to confirm doc shapes (`role_codes`, `account_status`, `patent_id` links).
- Storage: confirm bucket name matches `FIREBASE_STORAGE_BUCKET`; check blob prefixes `patents/{id}/files/`, `templates/{type}/`.

## 8. Performance notes

- Firestore list helpers cap at 100–500 docs — paginate client-side or add query filters for large tenants.
- `recharts` + `FullCalendar` are the heaviest frontend deps; avoid importing them on the login bundle (they're already route-split via pages).
- Backend Docker image is large (LibreOffice) — expected; don't remove without replacing DOCX→PDF rendering.
