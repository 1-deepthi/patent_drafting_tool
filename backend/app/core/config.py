from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_name: str = 'Patent Filing & Lifecycle Management Platform API'
    environment: str = 'development'
    firebase_project_id: str = ''
    firebase_service_account_path: str = 'secrets/firebase-service-account.json'
    firebase_storage_bucket: str = ''
    firebase_emulator_host: str = ''
    bootstrap_admin_email: str = ''
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    allowed_hosts: str = '*'
    max_upload_size_bytes: int = 10 * 1024 * 1024
    blocked_upload_extensions: str = '.exe,.bat,.cmd,.sh,.msi,.com,.dll,.scr,.jar'
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-2.0-flash'
    ai_provider: str = 'stub'

    @property
    def blocked_extensions(self) -> tuple[str, ...]:
        return tuple(x.strip().lower() for x in self.blocked_upload_extensions.split(',') if x.strip())

settings = Settings()
