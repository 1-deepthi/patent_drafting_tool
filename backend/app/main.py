from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Patent Platform API ({} environment)", settings.environment)
    yield
    await engine.dispose()
    logger.info("Shut down cleanly")


app = FastAPI(
    title="Patent Filing & Lifecycle Management Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Required by Authlib's Starlette integration to hold the transient OAuth
# state/nonce during the Google redirect round-trip. See config.session_secret.
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

# Routers are added here as each phase builds them, e.g.:
# from app.api import documents
from app.api import ai, auth, basic_info, documents, patents, questionnaire, rbac, teams  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(rbac.router, prefix="/api/rbac", tags=["rbac"])
app.include_router(teams.router, prefix="/api/teams", tags=["teams"])
app.include_router(patents.router, prefix="/api/patents", tags=["patents"])
# Nested under /api/patents/{id}/... — sub-resources of a patent application,
# not separate top-level resources.
app.include_router(basic_info.router, prefix="/api/patents", tags=["basic-info"])
app.include_router(questionnaire.router, prefix="/api/patents", tags=["questionnaire"])
app.include_router(ai.router, prefix="/api/patents", tags=["ai-drafting"])
app.include_router(documents.router, prefix="/api/patents", tags=["documents"])


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Confirms the API is up and can reach the database."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:  # noqa: BLE001 — deliberately broad for a health check
        logger.error("Database health check failed: {}", exc)
        db_status = "unreachable"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "environment": settings.environment,
    }
