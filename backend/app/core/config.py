from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/patent_platform"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # JWT session tokens
    jwt_secret: str = "change-this-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30  # 30-minute inactivity timeout, per spec

    # Starlette SessionMiddleware secret — holds ONLY the transient OAuth
    # state/nonce cookie during the Google redirect round-trip. Unrelated to
    # the stateless JWT above; nothing app-level is stored in this session.
    session_secret: str = "change-this-to-a-different-long-random-string"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # "stub" (default, offline-safe placeholder generator) or "gemini" (real
    # calls, requires gemini_api_key and network access to
    # generativelanguage.googleapis.com). See app/services/ai/factory.py.
    ai_provider: str = "stub"

    # Cloudflare R2
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "patent-platform-files"
    r2_endpoint_url: str = ""

    # "local" (default, offline-safe filesystem storage - what every live
    # verification in this project runs against) or "r2" (real Cloudflare
    # R2, requires the r2_* settings above and network access to R2's
    # endpoint, which this sandbox doesn't have). See
    # app/services/storage/factory.py.
    storage_provider: str = "local"
    local_storage_path: str = "./storage_data"

    # LibreOffice binary used for DOCX -> PDF conversion (headless). See
    # app/services/document_service.py.
    libreoffice_binary: str = "soffice"
    libreoffice_timeout_seconds: int = 60

    # Email (provider TBD)
    email_provider_api_key: str = ""

    # Redis — not used until the Phase 6/7 Celery trigger points are hit
    redis_url: str = ""

    # App
    environment: str = "development"
    cors_origins: str = "http://localhost:5173"
    frontend_url: str = "http://localhost:5173"

    # Dev-only login bypass (see app/api/auth.py) — issues a real JWT without
    # going through Google, so RBAC can be tested before Google OAuth
    # credentials exist. Hard-gated: only ever active when environment is
    # "development" AND this flag is explicitly true. Never enable in
    # staging/production.
    dev_login_enabled: bool = False

    # File upload limits — per spec: 10 MB max, executables blocked
    max_upload_size_bytes: int = 10 * 1024 * 1024
    blocked_upload_extensions: tuple[str, ...] = (
        ".exe", ".bat", ".cmd", ".sh", ".msi", ".com", ".dll", ".scr", ".jar",
    )


settings = Settings()
