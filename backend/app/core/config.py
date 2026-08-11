from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Unsafe development adapters are fail-closed in production."""

    model_config = SettingsConfigDict(
        env_prefix="PKA_",
        extra="ignore",
        str_strip_whitespace=True,
    )

    app_name: str = "Project Knowledge Assistant API"
    environment: Literal["development", "test", "production"] = "development"
    repository_backend: Literal["memory", "postgres"] = "memory"
    auth_mode: Literal["dev_headers"] = "dev_headers"
    database_host: str | None = Field(default=None, min_length=1)
    database_port: int | None = Field(default=None, ge=1, le=65_535)
    database_name: str | None = Field(default=None, min_length=1)
    database_user: str | None = Field(default=None, min_length=1)
    database_password_file: Path | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_connect_timeout_seconds: int = Field(default=2, ge=1, le=10)
    database_pool_timeout_seconds: int = Field(default=2, ge=1, le=10)
    database_statement_timeout_ms: int = Field(default=2_000, ge=100, le=30_000)

    @model_validator(mode="after")
    def validate_runtime_adapters(self) -> "Settings":
        if self.environment == "production":
            if self.repository_backend == "memory":
                raise ValueError("The in-memory repository is forbidden in production")
            if self.auth_mode == "dev_headers":
                raise ValueError("Development header identity is forbidden in production")

        if self.repository_backend == "postgres":
            required_settings = {
                "PKA_DATABASE_HOST": self.database_host,
                "PKA_DATABASE_PORT": self.database_port,
                "PKA_DATABASE_NAME": self.database_name,
                "PKA_DATABASE_USER": self.database_user,
                "PKA_DATABASE_PASSWORD_FILE": self.database_password_file,
            }
            missing = [name for name, value in required_settings.items() if value is None]
            if missing:
                raise ValueError(
                    "PostgreSQL repository configuration is incomplete; missing: "
                    + ", ".join(missing)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

