from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Unsafe development adapters are fail-closed in production."""

    model_config = SettingsConfigDict(env_prefix="PKA_", extra="ignore")

    app_name: str = "Project Knowledge Assistant API"
    environment: Literal["development", "test", "production"] = "development"
    repository_backend: Literal["memory"] = "memory"
    auth_mode: Literal["dev_headers"] = "dev_headers"

    @model_validator(mode="after")
    def reject_development_adapters_in_production(self) -> "Settings":
        if self.environment == "production":
            if self.repository_backend == "memory":
                raise ValueError("The in-memory repository is forbidden in production")
            if self.auth_mode == "dev_headers":
                raise ValueError("Development header identity is forbidden in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

