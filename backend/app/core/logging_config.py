"""Configures Loguru's sinks based on environment — Phase 10.

Development/test: untouched — Loguru's default pretty console sink,
exactly what every earlier phase's live verification already ran
against. Changing this for local dev would be a pure regression with no
upside.

Production: re-added as one-line JSON per record (`serialize=True`) so a
PaaS log collector (Koyeb's, or whatever sits downstream of it) can parse
fields — `request_id` in particular, bound by
app/core/middleware.py::RequestIDMiddleware — instead of grep-ing
human-formatted text.
"""
import sys

from loguru import logger

from app.core.config import settings


def configure_logging() -> None:
    if settings.environment != "production":
        return
    logger.remove()
    logger.add(sys.stdout, level="INFO", serialize=True, backtrace=False, diagnose=False)
