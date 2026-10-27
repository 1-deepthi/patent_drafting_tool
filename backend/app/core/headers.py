"""Security headers for every API response.

These mirror the headers nginx sets for the static frontend
(`frontend/nginx.conf`). HSTS is left to the hosting platform: the API is
often served over plain HTTP in local development, where a preload-style
header is noise rather than protection.

The middleware is pure ASGI and sets headers on the response message itself,
so it works for responses FastAPI never sees: CORS preflights, the body
guard's 413, and `TrustedHostMiddleware`'s 400.
"""

DEFAULT_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {name.lower() for name, _ in message.get("headers", [])}
                headers = list(message.get("headers", []))
                for name, value in DEFAULT_HEADERS:
                    encoded_name = name.lower().encode("latin-1")
                    if encoded_name not in existing:
                        headers.append((encoded_name, value.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
