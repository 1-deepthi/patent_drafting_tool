#!/bin/sh
# Runs on every container start (see Dockerfile's ENTRYPOINT).
#
# Legacy SQL path: applies any pending Alembic migrations before the app
# starts serving traffic — same two-step sequence GETTING_STARTED.md has
# always documented as a manual `alembic upgrade head` followed by
# `uvicorn ...`, just automated for a container that doesn't have a human
# running commands. Runs only when alembic is installed AND DATABASE_URL is
# set, so the check is a no-op rather than a boot failure elsewhere.
#
# Active Firebase path: there is no SQL database to migrate (Firestore needs
# no migrations and alembic is intentionally absent from requirements.txt),
# so this step is skipped and the app boots straight into serving traffic.
#
# Single-instance assumption: this project targets one backend instance
# (see config.py's Redis/rate-limiter notes) so there's no concurrent-
# migration race today. If a future phase scales to multiple replicas,
# this should move to a separate release-phase step (a one-off "migrate"
# job run before the new replicas start) rather than every replica racing
# `alembic upgrade head` on boot — flag this if that phase arrives.
set -e

if command -v alembic >/dev/null 2>&1 && [ -n "$DATABASE_URL" ]; then
    echo "Applying database migrations..."
    alembic upgrade head
else
    echo "Skipping Alembic migrations (no alembic binary or DATABASE_URL — Firebase runtime)."
fi

echo "Starting application..."
exec "$@"
