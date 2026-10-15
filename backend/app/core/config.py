"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration; secrets must come from the environment."""

    app_name: str = "SITARA API"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    session_ttl_seconds: int = 43_200
    login_rate_limit_hmac_key: SecretStr | None = None
    login_rate_limit_max_attempts: int = Field(default=10, ge=1, le=1000)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1, le=86_400)
    login_rate_limit_statement_timeout_ms: int = Field(default=2_000, ge=100, le=30_000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings; clear cache in tests when environment changes."""
    return Settings()
