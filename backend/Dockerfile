# --- builder: install Python deps into an isolated venv -------------------
FROM python:3.13-slim AS builder

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --- runtime: slim image, no build toolchain, non-root user ----------------
FROM python:3.13-slim

# LibreOffice is a hard requirement for real PDF conversion (see
# app/services/document_service.py) — installed only in this stage, not the
# builder, so the pip-install layer above stays cache-friendly and
# independent of this apt layer. This is the single biggest contributor to
# final image size; there's no way around it while DOCX->PDF conversion
# shells out to headless LibreOffice rather than a pure-Python renderer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=appuser:appuser . .
RUN chmod +x docker-entrypoint.sh

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

# Applies pending Alembic migrations, then execs whatever CMD is given below
# — see docker-entrypoint.sh's docstring for the single-instance assumption
# behind running migrations on every boot.
ENTRYPOINT ["./docker-entrypoint.sh"]

# gunicorn as the process manager (auto-restarts a crashed worker, handles
# graceful reload) running real async Uvicorn workers underneath — the
# standard production combo for an ASGI app; plain `uvicorn --workers N`
# has no supervisor of its own. 4 workers is a reasonable default for a
# single Koyeb-sized container; override via docker run/compose command,
# or set $WEB_CONCURRENCY if you swap this for gunicorn's own env-driven
# config later.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--timeout", "120"]
