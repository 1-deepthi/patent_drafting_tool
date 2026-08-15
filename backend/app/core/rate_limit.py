"""Rate limiting — Phase 10, via slowapi (a Starlette wrapper over the
`limits` library).

Storage is in-memory (slowapi's default) — per-process, not shared across
replicas. That's the same trade-off `config.py` already documents for
Celery/Redis: fine for a single instance, and this app has no shared
Redis today. If Redis is ever added for the deferred Phase 6/7 Celery
trigger, point this at it too (`Limiter(..., storage_uri="redis://...")`)
rather than standing up a second Redis use case just for this.

`settings.rate_limit_enabled=False` is an escape hatch for local dev/CI
so limits never cause test flake — tests that want to exercise the limiter
set it back on explicitly (see tests/test_hardening.py).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    enabled=settings.rate_limit_enabled,
)
