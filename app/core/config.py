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
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver", "api"]
    rate_limit_per_minute: int = Field(default=30, ge=1, le=10_000)

    serpapi_key: str | None = None
    enable_serpapi: bool = False
    enable_mercadolibre: bool = True
    enable_local_csv: bool = True
    enable_sodimac: bool = True
    enable_easy: bool = True
    enable_falabella: bool = True
    enable_paris: bool = True
    enable_construmart: bool = True

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

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def parse_csv_or_list(cls, value):
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
