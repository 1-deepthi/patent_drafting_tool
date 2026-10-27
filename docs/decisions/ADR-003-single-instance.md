# ADR-003: Single backend instance

## Status
Accepted — amended for the Firestore-only runtime (ADR-005).

## Date
2026-10-16 (amended 2026-10-27)

## Context
The backend runs document generation inside the API process: a request
renders a DOCX and may launch a headless LibreOffice subprocess to convert it
to PDF. There is no job queue, no distributed lock, and no shared cache; work
either completes inside the request or is recorded as a failed generation
job. The deployment target is a single container on a PaaS free/starter tier
(see `DEPLOYMENT.md`).

The original version of this ADR also cited in-memory rate limiting and
boot-time Alembic migrations. Both are gone with the SQL stack: Firestore
needs no migrations, and the Firebase runtime has no in-app rate limiter.
The single-instance constraint survives for the reasons above.

## Decision
Run exactly one backend replica. Multi-instance support is explicitly
deferred, not accidentally missing.

## Alternatives Considered

### Add a job queue + object-store-backed generation, then scale out
- Pros: correct under autoscaling; generation stops competing with request
  handling for CPU and file descriptors.
- Cons: adds a broker (Redis/Cloud Tasks), a worker image, retry semantics,
  and a second deployment unit — real work that nothing currently requires.
- Deferred: revisit when document volume or availability requirements demand
  a second replica.

### Multi-replica with the current code
- Pros: more capacity for ordinary reads.
- Cons: every replica spawns its own LibreOffice processes against the same
  CPU budget, and there is no shared coordination for long-running jobs;
  capacity planning becomes guesswork.
- Rejected: predictable single-container behaviour is better than silently
  oversubscribed replicas.

## Consequences
- `docker-compose.yml`, the Dockerfile, and the deployment docs describe one
  backend service. Do not raise `replicas` or worker count without first
  moving document generation off the request path.
- The Docker image runs two Gunicorn/Uvicorn workers (down from four) so the
  worst case is two concurrent LibreOffice subprocesses per container.
- There is no in-app rate limiting in the Firebase runtime. Put request
  limits at the platform edge (PaaS/WAF/Firebase quotas) before exposing the
  API publicly; add application-level limiting only with a shared store.
