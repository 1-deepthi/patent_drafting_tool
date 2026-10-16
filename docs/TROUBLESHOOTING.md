# Troubleshooting

Symptom-first fixes for local development. Setup walkthrough: [`GETTING_STARTED.md`](./GETTING_STARTED.md). Design context: [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Ports already in use

Developer machines often run other projects on the same ports this stack defaults to (`8000` backend, `5432` Postgres, `5173` frontend). Symptoms: `uvicorn` fails with `address already in use`, Compose fails to bind, or `http://localhost:8000/health` returns HTML from an unrelated app.

```powershell
# Find what owns a port:
netstat -ano | Select-String ":8000 "
Get-Process -Id <PID>   # confirm it isn't something you need before touching it
```

- **Do not kill other projects' processes.** Run this stack on free ports instead:
  ```powershell
  # Backend on 8001 (from backend/, venv active):
  python -m uvicorn app.main:app --reload --port 8001
  ```
  Then set `VITE_API_URL=http://localhost:8001` in `frontend/.env` and restart `npm run dev` (`VITE_*` values bake at start).
- For Compose, remap ports in `docker-compose.yml` (e.g. `"8001:8000"`, `"5433:5432`) rather than stopping unrelated containers.

## Backend

| Symptom | Cause | Fix |
|---|---|---|
| `GET /health` → `503 degraded` with Firebase detail | Service-account path wrong, project ID mismatch, or no network to Firebase | Recheck `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT_PATH`, `secrets/` filename; unset `FIREBASE_EMULATOR_HOST` unless using the emulator |
| `401` on every API call | Missing/expired Firebase ID token | Re-login; confirm `Authorization: Bearer <token>` is sent (`src/lib/api.ts`) |
| `403 awaiting approval` | Account is `pending` | Ask an Admin to approve via Super Admin → Pending Approvals |
| `POST /api/auth/dev-login` → `404` | Dev login is legacy-SQL-only; absent from the Firebase router | Use Firebase Auth — this is expected, not a bug |
| `422 Unprocessable Entity` | Missing required body field | Compare against `API_OVERVIEW.md` payloads |
| CORS errors in browser console | Origin not in `CORS_ORIGINS` | Add the exact frontend origin; restart backend |
| `400` from TrustedHost | Host not in `ALLOWED_HOSTS` | Include `localhost,127.0.0.1` (or the real domain in prod) |
| Uploads fail | Bucket unset, size cap, or blocked extension | Check `FIREBASE_STORAGE_BUCKET`, `MAX_UPLOAD_SIZE_BYTES`, backend logs (non-prod includes the reason) |
| Draft returns placeholder text | Expected without `AI_PROVIDER=gemini` + `GEMINI_API_KEY` | Set both; otherwise the stub is the intended behavior (ADR-004) |

## Frontend

| Symptom | Cause | Fix |
|---|---|---|
| Blank page after `npm run dev` | `VITE_API_URL` points at a dead backend, or `5173` clash | Confirm backend URL/ports; only the login screen works without a backend |
| `tsc` unused-var errors | `noUnusedLocals` / `noUnusedParameters` | Remove unused imports/vars; run `npx tsc --noEmit` locally |
| `npm run lint` fails with "eslint: command not found" | No eslint config/deps committed yet | Expected — lint is advisory in CI until the eslint setup lands; don't work around it by installing globals |
| Stale API URL after `.env` edit | `VITE_*` bake at dev-server start / build time | Restart `npm run dev`, or rebuild the Docker image with a new `--build-arg` |

## Docker

| Symptom | Cause | Fix |
|---|---|---|
| Backend container exits immediately | `docker-entrypoint.sh` migration step fails (legacy path) or env missing | Run with `--env-file backend/.env`; check `docker logs`; without Firebase creds `/health` is `503` but the container must still serve HTTP |
| Frontend shows wrong API URL | `VITE_API_URL` baked at build time | Rebuild with the correct `--build-arg`; runtime `-e` cannot change it |
| Build is slow (backend) | LibreOffice layer (~largest layer, required for DOCX→PDF) | Expected; use BuildKit layer caching (`docker.yml` uses GHA cache) |
| `docker compose up` port conflict | Another Postgres/backend on `5432`/`8000` | Remap ports; never stop unrelated containers to win a port |

## CI

| Symptom | Cause | Fix |
|---|---|---|
| Docker workflow fails at "Set up job" with `Unable to resolve action` | Pinned action repo renamed or mistyped (this bit us with `docker/build-action` vs `docker/build-push-action`) | Verify the action repo exists; keep pins in `dependabot.yml` scope |
| `backend-legacy-suite` red | Expected during the Firebase migration (targets archived SQL API) | Advisory job (`continue-on-error`); realign tests to the Firebase path instead of deleting them |
| `docs-health` red | Missing community file or secret-looking file in tree | Add the file, or remove the secret and rotate it (deleting a commit is not enough) |

Still stuck? See [`SUPPORT.md`](../SUPPORT.md) — include commit SHA, OS, Python/Node versions, and redacted logs.
