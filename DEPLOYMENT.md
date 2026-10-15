# Deployment Guide

Phase 10 output. Written against the stack referenced elsewhere in this
repo (`backend/.env.example`'s "Neon in production" comment, and the
Koyeb-shaped assumptions in `app/services/storage/local_provider.py` and
`docs/GETTING_STARTED.md`): **Koyeb** for both containers, **Neon** for
Postgres, **Cloudflare R2** for file storage. The steps below generalize
to any Dockerfile-based PaaS (Render, Fly.io, Railway, ECS, ...) — swap
the Koyeb-specific dashboard steps for your platform's equivalent.

None of this has been deployed or live-tested against a real Koyeb/Neon
account in this phase — there's no network access to either from this
build environment, the same limitation the Gemini/R2 integrations hit in
earlier phases. What IS verified: both Dockerfiles build on the
documented base images' own conventions and were reviewed line-by-line
against this repo's actual entrypoints, and every setting they depend on
is covered by `app/core/startup_checks.py`'s tests. Docker itself isn't
installed in this build sandbox, so `docker build` was not run — treat
that as this phase's version of the "GEMINI_API_KEY not set" caveat prior
phases carried forward until someone with real credentials/tooling
verifies it.

## 1. Provision the database (Neon)

1. Create a Neon project and copy its pooled connection string.
2. Rewrite it for asyncpg: Neon gives you `postgresql://...`; this app
   needs `postgresql+asyncpg://...` (same string, different scheme
   prefix — see `DATABASE_URL` in `.env.example`).
3. Migrations run automatically on container boot (see §3) — nothing to
   run manually against Neon first.

## 2. Provision storage (Cloudflare R2)

Already documented in `.env.example`; the one Phase 10 addition is that
`STORAGE_PROVIDER=local` is now a **hard startup failure in production**
(`app/core/startup_checks.py`) rather than a silent footgun — Koyeb
instances don't share a disk and don't persist one across redeploys, so
local storage would quietly lose every uploaded file. Set
`STORAGE_PROVIDER=r2` and fill in the five `R2_*` variables before
deploying.

## 3. Deploy the backend (Koyeb)

1. Point Koyeb at this repo, root directory `backend/`, build method
   Dockerfile (`backend/Dockerfile`).
2. Set every variable from `backend/.env.example` in Koyeb's environment
   settings — **with production values, not the checked-in placeholders**.
   At minimum, generate real secrets:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   Run it twice — `JWT_SECRET` and `SESSION_SECRET` must be different
   values (checked by `startup_checks.py`; a shared secret would let a
   forged OAuth state cookie double as a forged session token).
3. Required production-specific values (the exact list
   `app/core/startup_checks.py` enforces — the container will refuse to
   start and log every violation if any of these are wrong):
   - `ENVIRONMENT=production`
   - `DEV_LOGIN_ENABLED=false`
   - `JWT_SECRET` / `SESSION_SECRET` — real random values, ≥32 chars, not
     equal to each other, not the checked-in placeholders
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — real values
   - `GOOGLE_REDIRECT_URI` — `https://` and pointing at the real backend
     domain's `/api/auth/google/callback`
   - `FRONTEND_URL` — `https://` and pointing at the real frontend domain
   - `CORS_ORIGINS` — the real frontend origin, not `*` and not a
     `localhost` value
   - `ALLOWED_HOSTS` — the real backend domain (Koyeb gives you one like
     `your-app.koyeb.app`, or your custom domain once attached)
   - `STORAGE_PROVIDER=r2` with the five `R2_*` values filled in
4. Expose port `8000`; Koyeb's health check should hit `GET /health`
   (the existing endpoint from earlier phases — Phase 10 didn't change
   its contract, only added the security headers it now also carries).
5. Deploy. The container's entrypoint (`docker-entrypoint.sh`) applies
   any pending Alembic migrations before gunicorn starts serving — watch
   the boot logs for either a clean `alembic upgrade head` or, if a
   config check failed, the specific list of problems
   `startup_checks.py` found (logged, then the process exits non-zero
   rather than serving traffic insecurely).

### A note on scale

This app currently assumes **one backend instance**. Two places would
need attention before running more than one replica:

- **Rate limiting** (`app/core/rate_limit.py`) is in-memory per-process —
  each replica would enforce its own separate limit rather than one
  shared one. Fix: point slowapi at Redis once Redis exists (still
  gated on the Phase 6/7 Celery trigger noted in `config.py` and
  `docker-compose.yml`).
- **Migrations on boot** (`docker-entrypoint.sh`) would have every
  replica racing `alembic upgrade head` simultaneously on a deploy. Fix:
  move to a separate one-off "release" step that runs once before new
  replicas start, instead of inside each replica's own entrypoint.

Neither is a problem at one instance, which is what Koyeb's free/starter
tiers give you by default — flagged here so it's a deliberate choice to
revisit, not a surprise.

## 4. Deploy the frontend

Two reasonable options — this repo supports both, pick one:

**A. Static hosting** (Koyeb static sites, Cloudflare Pages, Vercel,
Netlify): build with `npm run build` inside `frontend/`, setting
`VITE_API_URL` to the backend's real HTTPS URL as a build-time
environment variable (Vite bakes it into the bundle at build time — see
`frontend/Dockerfile`'s comment on the same constraint). Serve
`frontend/dist/`, with a catch-all rewrite to `index.html` for
client-side routing — most static hosts have this as a one-line SPA
setting.

**B. Container** (`frontend/Dockerfile`, added this phase): builds the
same Vite bundle, then serves it via nginx with the SPA fallback and
security headers already configured (`frontend/nginx.conf`). Deploy this
to Koyeb (or any container host) exactly like the backend, but with
`VITE_API_URL` passed as a **build arg**, not a runtime env var — Koyeb's
Dockerfile build UI supports build args directly.

Either way, once deployed, go back to Google Cloud Console and add the
real frontend origin to the OAuth client's authorized JavaScript origins,
and the real backend callback URL to authorized redirect URIs — both
still point at `localhost` from local development until updated.

## 5. Verify

1. `GET https://<backend-domain>/health` → `200`, and inspect headers for
   `x-content-type-options`, `x-frame-options`, `x-request-id` — confirms
   the hardening middleware is active.
2. Load the frontend, sign in with a real Google account (dev-login is
   off in production — this is the only way in now), confirm the
   INNOVATOR happy path from earlier phases' manual walkthroughs still
   works end to end against the deployed backend.
3. Confirm rate limiting: 11 rapid requests to `/api/auth/google/login`
   should return `429` on the 11th (only worth checking once; don't
   script this against a real deployment repeatedly, it'll lock out
   real users hitting the same limit).

## What Phase 10 deliberately did NOT do

- **No secrets manager integration** (Koyeb's own env var storage is used
  as-is, same as every `.env` file already committed as a template in
  this repo — not a regression, just not upgraded).
- **No CDN in front of the frontend** — nginx's own caching headers
  (`frontend/nginx.conf`) are the extent of it; add Cloudflare in front
  later if traffic warrants it.
- **No multi-instance/autoscaling support** — see "A note on scale" above.
- **No automated deployment** (no `koyeb deploy` step in CI) — CI
  (`.github/workflows/ci.yml`) runs tests and builds only; wiring it to
  actually deploy on merge to `main` is a reasonable Phase 11 candidate
  once there's a real Koyeb account/API token to give it.
