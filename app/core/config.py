from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion tipada y centralizada de la aplicacion."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["local", "test", "production"] = "local"
    database_url: str = "sqlite:///./smart_buyer.db"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = Field(default=900, ge=30, le=86_400)

    admin_api_key: str = ""
    # Firma enlaces de alertas y seudonimiza IPs del feedback. Si falta, se usa ADMIN_API_KEY.
    app_secret_key: str = ""
    # URL publica del API para enlaces en emails (via frontend: http://localhost:3000/api).
    public_api_url: str = "http://localhost:8000"
    # Proxies cuyo X-Forwarded-For se acepta (p. ej. el contenedor del frontend).
    trusted_proxy_cidrs: list[str] = ["127.0.0.1/32", "::1/128"]
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver", "api"]
    rate_limit_per_minute: int = Field(default=30, ge=1, le=10_000)
    feedback_limit_per_minute: int = Field(default=20, ge=1, le=1_000)
    alert_create_limit_per_hour: int = Field(default=5, ge=1, le=1_000)
    alert_max_active_per_email: int = Field(default=10, ge=1, le=100)
    alert_max_new_per_email_per_day: int = Field(default=3, ge=1, le=50)
    feedback_max_offer_age_days: int = Field(default=7, ge=1, le=90)

    serpapi_key: str | None = None
    mercadolibre_client_id: str = ""
    mercadolibre_client_secret: str = ""
    enable_serpapi: bool = False
    enable_mercadolibre: bool = True
    enable_local_csv: bool = True
    enable_sodimac: bool = True
    enable_easy: bool = True
    enable_falabella: bool = True
    enable_paris: bool = True
    # Construmart carga precios por zona via JavaScript: el HTML no trae precios.
    enable_construmart: bool = False

    default_country: str = "cl"
    default_language: str = "es"
    request_timeout_seconds: int = Field(default=25, ge=3, le=90)
    search_timeout_seconds: int = Field(default=40, ge=5, le=180)
    price_freshness_hours: int = Field(default=24, ge=1, le=168)
    user_agent: str = "CompradorInteligente/5.0 contacto@comprador-inteligente.cl"

    alert_email_from: str = ""
    alert_email_password: str = ""
    alert_email_smtp: str = "smtp.gmail.com"
    alert_email_port: int = Field(default=587, ge=1, le=65_535)

    @property
    def signing_secret(self) -> str:
        return (self.app_secret_key or self.admin_api_key).strip()

    @field_validator("cors_origins", "trusted_hosts", "trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_csv_or_list(cls, value):
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
