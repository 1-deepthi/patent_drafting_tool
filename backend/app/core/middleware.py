"""Cross-cutting response middleware — Phase 10.

Both middlewares are stateless and apply to every response, including
error responses (they wrap `call_next`, not any specific route), so they
don't interact with the per-route auth/RBAC dependencies in app/api/deps.py.
"""
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Standard defensive response headers. No per-route config — same
    headers on every response.

    HSTS is opt-in via the `hsts` flag (see app/main.py: only enabled
    when settings.environment == "production") because it actively
    breaks plain-HTTP local development if sent over http://localhost.
    """

    def __init__(self, app, hsts: bool = False):
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        if self._hsts:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Stamps every request/response with X-Request-ID (reusing one the
    caller/proxy already supplied, so it survives a hop through a load
    balancer) and binds it into Loguru's context for the duration of the
    request, so every log line emitted while handling it — including from
    deep inside a service — carries the same id without threading it
    through every function signature.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        with logger.contextualize(request_id=request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
