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
# app/services/documents.py) — installed only in this stage, not the builder,
# so the pip-install layer above stays cache-friendly and independent of this
# apt layer. This is the single biggest contributor to final image size;
# there's no way around it while DOCX->PDF conversion shells out to headless
# LibreOffice rather than a pure-Python renderer. DOCX generation itself works
# without it, and a missing `soffice` surfaces as a failed generation job
# rather than a broken service.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# /health returns 503 until Firebase credentials resolve (ADR-005), so the
# container is "up" but reported unhealthy until backend/.env is complete or
# the Firebase service-account key is mounted.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

# No entrypoint script: there are no migrations to apply (Firestore needs
# none) and no boot-time secret materialisation. Configuration comes from the
# environment, exactly as pydantic-settings reads it.
#
# gunicorn as the process manager (auto-restarts a crashed worker, handles
# graceful reload) running async Uvicorn workers underneath. All application
# state lives in Firebase, so worker count is only a capacity decision; keep
# it modest because each worker can spawn a LibreOffice subprocess when
# converting DOCX to PDF. Override with `docker run ... <command>` if needed.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--timeout", "120"]
