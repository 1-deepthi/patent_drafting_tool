"""Request-size enforcement shared by middleware and upload handlers.

Vercel rejects request bodies above 4.5 MB before the app sees them, so the
app has to stay below that on its own. `Settings.upload_limit_bytes` carries
the effective per-file limit; this module turns it into HTTP responses and
guards JSON/multipart bodies early.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import MIB, settings


def human_size(size: int) -> str:
    if size >= MIB and size % MIB == 0:
        return f"{size // MIB} MB"
    return f"{size / MIB:.1f} MB"


def upload_limit_detail() -> str:
    return (
        "Files are limited to "
        f"{human_size(settings.upload_limit_bytes)} on this deployment."
    )


def request_body_limit_detail() -> str:
    return (
        "Request body is too large. This deployment accepts uploads up to "
        f"{human_size(settings.upload_limit_bytes)}."
    )


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies before FastAPI reads or buffers them.

    FastAPI still validates per-file size after reading (see `_read_upload`),
    which covers chunked requests that omit Content-Length.
    """

    async def dispatch(self, request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            raw_length = request.headers.get("content-length")
            if raw_length:
                try:
                    length = int(raw_length)
                except ValueError:
                    length = -1
                if length > settings.request_body_limit_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": request_body_limit_detail()},
                    )
        return await call_next(request)
