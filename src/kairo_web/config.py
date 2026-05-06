"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic import EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime config. Override via environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # Core
    KAIRO_SECRET_KEY: str
    KAIRO_DATABASE_URL: str = "sqlite:///./dev.db"
    KAIRO_BASE_URL: str = "http://localhost:8001"
    KAIRO_OWNER_EMAIL: EmailStr
    KAIRO_TIMEZONE: str = "Europe/London"

    # Email (Resend). Empty API key ⇒ log-only mode for local dev.
    RESEND_API_KEY: str = ""
    RESEND_FROM_DOMAIN: str = "kairo.example.com"

    # Logging
    LOG_LEVEL: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton accessor. Tests can call `get_settings.cache_clear()`."""
    return Settings()  # type: ignore[call-arg]
