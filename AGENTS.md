# AGENTS.md

Guidance for AI coding agents working with or on patent_drafting_tool.

## Stack at a glance

- Backend: FastAPI + Firebase Admin (Auth, Firestore, Storage), Python 3.11+ (Docker: 3.13). Active routers are `app/api/auth.py` + `app/api/resources.py` only.
- Frontend: React 18 + Vite 6 + TypeScript `strict` + Tailwind 3, Node 20.
- Decisions live in `docs/decisions/` (ADRs) — read the relevant one before changing auth, data, deployment, or AI code.

## Commands

```powershell
# Backend (from backend/, venv active)
python -m uvicorn app.main:app --reload --port 8000
python -m compileall app
python -m pytest -q            # legacy SQL suite: needs Postgres + legacy mounts (see below)

# Frontend (from frontend/)
npm ci
npm run dev                    # :5173
npm run build                  # tsc -b && vite build
```

## Conventions

- Conventional commits with one type per commit; atomic commits (~100 lines ideal, ~300 max) — see `CONTRIBUTING.md` → Commit discipline, including the 8-commit stack example.
- Backend guards: `active_user` → `require_roles(*codes)` / `is_admin()`; visibility via `services/repository.py`. Never trust client-supplied roles.
- Frontend: all HTTP through `lib/api.ts` (`apiFetch`/`apiUpload`/`apiDownload`); gating through `ProtectedRoute`; loading/empty UI through `components/LoadingState` / `components/EmptyState` (always centred, `role="status"`).
- Loading states: full/panel loads use `<LoadingState />`, tight inline slots use `<LoadingState compact />`.

## Boundaries (do not cross without an approved issue)

- The legacy Postgres/SQLAlchemy code (`app/models/`, `alembic/`, unmounted `api/*` routers, SQL services, `tests/`) is reference-only. Do not extend it, do not delete it, do not build features on it.
- Never commit `.env`, `secrets/*.json`, `dist/`, `venv/`, `node_modules/`, or model binaries.
- Never widen CORS/hosts, weaken upload validation, or bypass `ScopeGuard`-equivalent auth checks for convenience.
- `ref-repos/` holds ignored reference clones for inspiration — never import from it, never commit it.
- Single backend instance assumption (ADR-003): no multi-replica changes without the Redis + release-step fixes.
- Generated patent text is draft-only, never legal advice — keep the warning on every stub/AI surface.
