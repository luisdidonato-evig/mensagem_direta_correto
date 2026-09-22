from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Evig Direct Messages API"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./evig.db"
    auto_create_schema: bool = True
    cors_origins: str = "http://localhost:5173"
    redis_url: str = "redis://localhost:6379/0"
    dispatch_mode: str = "inline"
    pii_hash_secret: str = "change-me-in-production"

    audience_mode: str = "mock"
    audience_api_url: str = ""
    audience_api_token: str = ""
    audience_timeout_seconds: float = 10.0
    auth_enabled: bool = False
    # Formato: token:ROLE:organization_id,token2:ROLE:* (ROLE = ADMIN|OPERATOR|VIEWER)
    auth_tokens: str = ""
    handoff_webhook_url: str = ""
    handoff_webhook_secret: str = ""
    handoff_timeout_seconds: float = 5.0

    meta_mode: str = "mock"
    meta_graph_version: str = "v23.0"
    meta_access_token: str = ""
    meta_waba_id: str = ""
    meta_phone_number_id: str = ""
    meta_webhook_verify_token: str = "change-me"
    meta_app_secret: str = ""
    meta_webhook_forward_url: str = ""
    store_webhook_payloads: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("meta_mode")
    @classmethod
    def validate_meta_mode(cls, value: str) -> str:
        if value not in {"mock", "live"}:
            raise ValueError("META_MODE deve ser 'mock' ou 'live'")
        return value

    @field_validator("dispatch_mode")
    @classmethod
    def validate_dispatch_mode(cls, value: str) -> str:
        if value not in {"inline", "celery"}:
            raise ValueError("DISPATCH_MODE deve ser 'inline' ou 'celery'")
        return value

    @field_validator("audience_mode")
    @classmethod
    def validate_audience_mode(cls, value: str) -> str:
        if value not in {"mock", "http"}:
            raise ValueError("AUDIENCE_MODE deve ser 'mock' ou 'http'")
        return value

    def validate_live_meta(self) -> None:
        if self.meta_mode != "live":
            return
        missing = [
            name
            for name, value in {
                "META_APP_SECRET": self.meta_app_secret,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Configuração Meta incompleta: {', '.join(missing)}")

    def validate_runtime(self) -> None:
        self.validate_live_meta()
        if self.audience_mode == "http" and not self.audience_api_url:
            raise RuntimeError("AUDIENCE_API_URL é obrigatória no modo http")
        if self.auth_enabled and not self.auth_tokens.strip():
            raise RuntimeError("AUTH_TOKENS é obrigatório quando AUTH_ENABLED=true")
        if self.app_env == "production" and self.pii_hash_secret == "change-me-in-production":
            raise RuntimeError("PII_HASH_SECRET precisa ser alterado em produção")
        if self.app_env == "production" and not self.auth_enabled:
            raise RuntimeError("AUTH_ENABLED precisa estar ativo em produção")


@lru_cache
def get_settings() -> Settings:
    return Settings()
