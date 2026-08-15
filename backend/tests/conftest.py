"""Shared pytest fixtures for the backend test suite.

Critical ordering constraint: the DATABASE_URL and DEV_LOGIN_ENABLED env
vars MUST be set before any `app.*` module is imported, because
app/core/config.py's Settings() reads them at import time and
app/core/database.py builds its engine from that Settings instance
immediately. Do not move the imports below the os.environ block, and do
not import any app module at the top of a test file before conftest has
had a chance to run (pytest imports conftest.py first automatically, so
this is safe as long as this file keeps its import order).

Uses a real Postgres test database (patent_platform_test) — a full
async ORM/session behavior mismatch with sqlite makes sqlite not worth
the trade-off here, and Postgres is already a hard requirement for the
app itself (JSONB columns, etc). Run:
    createdb patent_platform_test  (or: psql -c "CREATE DATABASE patent_platform_test;")
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/patent_platform_test \
        alembic upgrade head
before running the suite the first time.
"""
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/patent_platform_test",
)
os.environ.setdefault("DEV_LOGIN_ENABLED", "true")
os.environ.setdefault("ENVIRONMENT", "development")
# Keep provider settings at their offline-safe defaults regardless of what a
# developer's local .env has set, so the suite never accidentally tries to
# call Gemini or R2 over the network.
os.environ["AI_PROVIDER"] = "stub"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["LOCAL_STORAGE_PATH"] = "./storage_data_test"
# Phase 10's rate limiter is off by default for the suite — most existing
# tests (test_auth.py especially) call dev-login far more than
# RATE_LIMIT_AUTH's 10/minute in a single run, and that's not what those
# tests are checking. tests/test_hardening.py flips app.core.rate_limit's
# `limiter.enabled` back on for the specific tests that exercise it, then
# restores it in a finally — same toggle-and-revert convention
# test_admin_rbac.py already uses for role_permissions grants.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.core.database as database_module
from app.core.config import settings

# Rebuild the app's engine/sessionmaker with NullPool. Without this, the
# engine's default pool holds asyncpg connections that get bound to
# whichever asyncio event loop was running when they were first checked
# out; pytest-asyncio's per-test loop handling then causes
# "attached to a different loop" / "another operation is in progress"
# errors as soon as more than one test touches the DB. NullPool opens a
# fresh connection per checkout and never reuses one across a loop
# boundary, which is the standard fix for this exact class of test flake.
# Reassigning the module's attributes (rather than just the names
# imported here) matters: app/core/database.py's own get_db() reads
# AsyncSessionLocal as ITS module global at call time, so this override
# is picked up by every Depends(get_db) route without touching any
# other file.
database_module.engine = create_async_engine(settings.database_url, poolclass=NullPool)
database_module.AsyncSessionLocal = async_sessionmaker(
    bind=database_module.engine, class_=AsyncSession, expire_on_commit=False,
)

from app.main import app  # noqa: E402 — must come after the engine override above
from app.seed import seed as seed_roles_and_permissions  # noqa: E402

engine = database_module.engine

# Tables that hold per-test data. Roles/permissions/users are seeded once
# per session (see seed_once fixture) and intentionally NOT truncated here
# — most tests create their own users via dev-login, which is idempotent
# per email, so leftover seed-only rows don't interfere. Tests that create
# their OWN throwaway users (most of them) get a clean slate on the
# business-data tables below every single test.
_DATA_TABLES = [
    "patent_applications",
    "teams",
    "team_members",
    "applicants",
    "inventors",
    "questionnaires",
    "questionnaire_versions",
    "ai_outputs",
    "documents",
    "document_versions",
    "document_generation_jobs",
    "comments",
    "files",
    "notifications",
    "calendar_events",
    "patent_assignments",
    "templates",
    "report_permissions",
    "audit_logs",
]


@pytest_asyncio.fixture(scope="session", autouse=True)
async def seed_once():
    """Seeds roles + permissions once for the whole test run (matches what
    a real deployment does exactly once via `python -m app.seed`)."""
    await seed_roles_and_permissions()
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_data_tables():
    """Truncates all business-data tables before each test so tests never
    depend on ordering or leak state into each other — this is the exact
    gap that caused the test-data confusion in Project_Handover_v10.md
    §7.12 (repeated manual setup runs silently accumulating stale rows
    the frontend then operated on by mistake). Users/roles/permissions
    are left alone; dev-login is idempotent per email so tests can log in
    freely without worrying about duplicate-user errors."""
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_DATA_TABLES)} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def client():
    """An httpx AsyncClient talking directly to the FastAPI app in-process
    (no real network hop, no need for uvicorn to be running)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def make_user(client):
    """Returns an async helper: await make_user("INNOVATOR", "a@test.dev") -> auth headers dict.
    Uses the real dev-login endpoint end-to-end (same code path the actual
    frontend uses), rather than minting JWTs by hand, so these tests also
    exercise the auth wiring itself."""

    async def _make(role_code: str, email: str, full_name: str = "Test User"):
        resp = await client.post(
            "/api/auth/dev-login",
            json={"role_code": role_code, "email": email, "full_name": full_name},
        )
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture(autouse=True)
def clean_storage_dir():
    """Files/documents created via the 'local' storage provider land on
    disk under LOCAL_STORAGE_PATH — wipe it between tests too, so a
    generated-document test never accidentally reads a file left behind
    by a previous test."""
    yield
    path = Path(os.environ["LOCAL_STORAGE_PATH"])
    if path.exists():
        shutil.rmtree(path)
