# Docker guide

## 1. Images

| Image | Dockerfile | Base | Purpose |
|---|---|---|---|
| Backend | `backend/Dockerfile` | `python:3.13-slim` (builder + runtime) | FastAPI via Gunicorn + Uvicorn workers |
| Frontend | `frontend/Dockerfile` | `node:20-slim` → `nginx:1.27-alpine` | Vite build → static serve with SPA fallback |

## 2. Backend image details

Stages:

1. **builder**: creates `/opt/venv`, `pip install -r requirements.txt`.
2. **runtime**: installs `libreoffice` + `ca-certificates` (required for DOCX→PDF via headless LibreOffice — the main size cost), creates non-root `appuser` (uid 1000), copies venv + source, `chmod +x docker-entrypoint.sh`, `USER appuser`.

```dockerfile
# Entrypoint runs `alembic upgrade head` only when alembic is installed AND
# DATABASE_URL is set (legacy SQL path); on the active Firebase runtime it
# skips migrations and boots straight into serving. Gunicorn comes from
# requirements.txt — the image cannot serve without it.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "app.main:app",
     "--worker-class", "uvicorn.workers.UvicornWorker",
     "--workers", "4",
     "--bind", "0.0.0.0:8000",
     "--access-logfile", "-", "--error-logfile", "-", "--timeout", "120"]
```

- `EXPOSE 8000`; `HEALTHCHECK` hits `http://localhost:8000/health` (30 s interval, 15 s start period).
- Env comes from `--env-file` or orchestrator vars (see `backend/.env.example`). `DATABASE_URL` override in Compose is legacy-only; Firebase uses `FIREBASE_*`.

Build + run:

```powershell
docker build -t patent-backend ./backend
docker run -p 8000:8000 --env-file backend/.env patent-backend
```

Verify: `GET http://localhost:8000/health` → `200` once Firebase is reachable.

## 3. Frontend image details

Stages:

1. **build** (`node:20-slim`): `npm ci`, copy source, bake `ARG VITE_API_URL` + force `VITE_DEV_LOGIN_ENABLED=false`, `npm run build` → `dist/`.
2. **serve** (`nginx:1.27-alpine`): copy `dist/` → `/usr/share/nginx/html`, copy `nginx.conf` → `/etc/nginx/conf.d/default.conf`.

- `EXPOSE 80`; `HEALTHCHECK` via `wget http://localhost/health`.
- `nginx.conf` provides SPA fallback (all routes → `index.html`) + caching/security headers.

Build + run:

```powershell
# VITE_API_URL is baked at build time — it cannot be changed at container run time.
docker build --build-arg VITE_API_URL=https://api.example.com -t patent-frontend ./frontend
docker run -p 8080:80 patent-frontend
```

Verify: open http://localhost:8080 → login page; confirm API calls hit the baked URL (DevTools Network).

## 4. Compose (local full-stack)

`docker-compose.yml` services:

| Service | Image | Ports | Notes |
|---|---|---|---|
| `postgres` | `postgres:17` | `5432:5432` | `patent_platform` DB, `pgdata` volume, `pg_isready` healthcheck. Legacy reference; Firebase path ignores it. |
| `backend` | Built from `./backend` | `8000:8000` | `env_file: ./backend/.env` + `DATABASE_URL` override to `postgres` host; `depends_on: postgres healthy`; `/health` healthcheck. |

```powershell
docker compose up --build
docker compose down -v  # also removes pgdata
```

Redis is intentionally absent (added only when long-running AI refinement needs a Celery broker).

## 5. Production notes

- Backend: expose `8000`, health check `GET /health`, single replica (in-memory rate limiting; boot migrations race with >1 replica). Set `ENVIRONMENT=production` + real Firebase/CORS/hosts values (see `DEPLOYMENT.md` §3).
- Frontend: pass the real backend URL as `VITE_API_URL` build arg; serve `dist/` statically or via the nginx image; add SPA rewrite (`/*` → `index.html`) on static hosts.
- Never bake secrets into images — pass via env at run time (backend) and keep `secrets/*.json` out of build contexts (`.dockerignore` covers it).
