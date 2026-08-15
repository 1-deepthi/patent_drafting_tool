#!/bin/sh
# Runs on every container start (see Dockerfile's ENTRYPOINT). Applies any
# pending Alembic migrations before the app starts serving traffic — same
# two-step sequence GETTING_STARTED.md has always documented as a manual
# `alembic upgrade head` followed by `uvicorn ...`, just automated for a
# container that doesn't have a human running commands.
#
# Single-instance assumption: this project targets one backend instance
# (see config.py's Redis/rate-limiter notes) so there's no concurrent-
# migration race today. If a future phase scales to multiple replicas,
# this should move to a separate release-phase step (a one-off "migrate"
# job run before the new replicas start) rather than every replica racing
# `alembic upgrade head` on boot — flag this if that phase arrives.
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Starting application..."
exec "$@"
