# ADR-003: Single backend instance (no shared rate limiting or coordinated migrations)

## Status
Accepted

## Date
2026-10-16

## Context
Two backend subsystems assume one running instance: rate limiting (`app/core/rate_limit.py`) is in-memory per process, and the container entrypoint (`backend/docker-entrypoint.sh`) runs `alembic upgrade head` on every boot. The production target (Koyeb free/starter tiers, see `DEPLOYMENT.md`) provides a single container by default.

## Decision
Run exactly one backend replica. Multi-instance support is explicitly deferred, not accidentally missing.

## Alternatives Considered

### Redis-backed rate limiting + one-off release step for migrations
- Pros: correct under autoscaling; standard practice.
- Cons: adds a Redis dependency (Compose, config, and hosting) that nothing else needs yet — Redis is deliberately gated on the Phase 6/7 Celery trigger noted in `docker-compose.yml`.
- Deferred: revisit when traffic or availability requirements demand a second replica.

### Multi-replica with current code
- Pros: more capacity.
- Cons: each replica enforces its own rate limit (N× effective limit) and all replicas race migrations on deploy.
- Rejected: silently wrong behavior.

## Consequences
- `docker-compose.yml` and deployment docs describe a single backend service; do not scale `replicas` without implementing the Redis + release-step fixes first.
- CI's Docker smoke test exercises the single-container boot path, which is the supported topology.
