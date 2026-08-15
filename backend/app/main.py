from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.database import engine
from app.core.logging_config import configure_logging
from app.core.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from app.core.rate_limit import limiter
from app.core.startup_checks import find_production_issues

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "production":
        issues = find_production_issues(settings)
        if issues:
            for issue in issues:
                logger.error("Production config check failed: {}", issue)
            raise RuntimeError(
                "Refusing to start in production with unsafe configuration:\n- "
                + "\n- ".join(issues)
            )
    logger.info("Starting Patent Platform API ({} environment)", settings.environment)
    yield
    await engine.dispose()
    logger.info("Shut down cleanly")


app = FastAPI(
    title="Patent Filing & Lifecycle Management Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler for anything not already caught by a route or
    FastAPI's own HTTPException/RequestValidationError handling (those are
    more specific and take priority, per Starlette's handler lookup — this
    only ever fires for genuinely unexpected errors). Full detail always
    goes to the logs (with the request's X-Request-ID for correlation);
    the response body only includes it outside production, so a stack
    trace / exception message never leaks to a client in prod.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.opt(exception=exc).error("Unhandled exception [request_id={}]", request_id)
    detail = (
        "Internal server error"
        if settings.environment == "production"
        else f"{type(exc).__name__}: {exc}"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": detail, "request_id": request_id},
    )


# --- Middleware stack --------------------------------------------------
# Starlette applies these outside-in on the request and inside-out on the
# response, in the reverse of registration order (last added == outermost).
# SecurityHeaders/RequestID are added last so they wrap every response,
# including ones produced by the exception handlers above.

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

# "*" (default) preserves every earlier phase's wide-open local-dev
# behavior; set ALLOWED_HOSTS in production (checked by startup_checks.py).
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[h.strip() for h in settings.allowed_hosts.split(",")],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    SecurityHeadersMiddleware, hsts=(settings.environment == "production")
)

# Routers are added here as each phase builds them, e.g.:
# from app.api import documents
from app.api import (  # noqa: E402
    ai,
    auth,
    basic_info,
    calendar,
    comments,
    documents,
    files,
    notifications,
    patents,
    questionnaire,
    rbac,
    reports,
    teams,
    templates,
)

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
app.include_router(comments.router, prefix="/api/patents", tags=["comments"])
app.include_router(files.router, prefix="/api/patents", tags=["files"])
app.include_router(calendar.router, prefix="/api/patents", tags=["calendar"])
# User-scoped, not nested under a patent — see app/api/notifications.py.
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
# Admin/Super Admin only — not nested under a patent (NEW, closes open item #24).
app.include_router(templates.router, prefix="/api/templates", tags=["templates"])
# Cross-patent aggregated view for the standalone Calendar page.
app.include_router(calendar.calendar_router, prefix="/api/calendar", tags=["calendar"])
# Phase 9 — dashboard + reports. Not nested under a patent: reports are
# cross-patent aggregates, scoped by visible_patents_query internally.
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(
    reports.permissions_router, prefix="/api/reports/permissions", tags=["reports"]
)


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
