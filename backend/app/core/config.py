from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

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
    mcp_reads_enabled: bool = False
    mcp_mutations_enabled: bool = False
    mcp_atlassian_enabled: bool = False
    mcp_jira_enabled: bool = False
    mcp_confluence_enabled: bool = False
    mcp_figma_enabled: bool = False
    mcp_grant_backend: Literal["disabled", "development_files"] = "disabled"
    mcp_atlassian_bearer_token_file: Path | None = None
    # A delegated Atlassian token covers exactly one site. When Jira and Confluence
    # are hosted on different sites they need different tokens; these two override
    # the provider-wide file for their binding and default to it when unset, so a
    # single-site deployment stays configured by the one file above.
    mcp_atlassian_jira_bearer_token_file: Path | None = None
    mcp_atlassian_confluence_bearer_token_file: Path | None = None
    # A credentials document carries the refresh token alongside the access token,
    # so the broker renews the grant itself instead of expiring into a manual
    # re-authorisation. Where one is configured it supersedes the bearer token file
    # for that binding; the plain files stay supported for providers issuing
    # long-lived personal tokens, which have nothing to refresh.
    mcp_atlassian_credentials_file: Path | None = None
    mcp_atlassian_jira_credentials_file: Path | None = None
    mcp_atlassian_confluence_credentials_file: Path | None = None
    mcp_atlassian_grant_tenant_id: str | None = Field(default=None, min_length=1, max_length=200)
    mcp_atlassian_grant_user_id: str | None = Field(default=None, min_length=1, max_length=200)
    mcp_figma_bearer_token_file: Path | None = None
    mcp_figma_credentials_file: Path | None = None
    # Figma authenticates a personal access token and an OAuth token by different
    # headers, and honours neither if the other is also present. The adapter sends
    # exactly one, so the kind has to be declared rather than guessed. Development
    # uses a personal token; per-user OAuth is the production shape.
    mcp_figma_credential_kind: Literal["personal_access_token", "oauth"] = (
        "personal_access_token"
    )
    mcp_figma_grant_tenant_id: str | None = Field(default=None, min_length=1, max_length=200)
    mcp_figma_grant_user_id: str | None = Field(default=None, min_length=1, max_length=200)
    mcp_atlassian_jira_cloud_id: UUID | None = None
    mcp_atlassian_confluence_cloud_id: UUID | None = None

    @model_validator(mode="after")
    def validate_runtime_adapters(self) -> "Settings":
        if self.mcp_mutations_enabled:
            raise ValueError("MCP mutations cannot be enabled by this release")
        if self.mcp_reads_enabled and self.repository_backend != "postgres":
            raise ValueError("Enabled MCP reads require the PostgreSQL audit repository")

        if self.environment == "production":
            if self.repository_backend == "memory":
                raise ValueError("The in-memory repository is forbidden in production")
            if self.auth_mode == "dev_headers":
                raise ValueError("Development header identity is forbidden in production")

        if self.mcp_jira_enabled and not self.mcp_atlassian_enabled:
            raise ValueError("The Jira MCP binding requires the Atlassian provider")
        if self.mcp_confluence_enabled and not self.mcp_atlassian_enabled:
            raise ValueError("The Confluence MCP binding requires the Atlassian provider")
        if self.mcp_jira_enabled and self.mcp_atlassian_jira_cloud_id is None:
            raise ValueError("The Jira MCP binding requires its server-side cloud ID")
        if self.mcp_confluence_enabled and self.mcp_atlassian_confluence_cloud_id is None:
            raise ValueError("The Confluence MCP binding requires its server-side cloud ID")
        # Atlassian issues one cloud ID per site covering both products: the two
        # values coincide on a single-site deployment and differ as soon as Jira and
        # Confluence live on separate sites. Each stays declared and injected on its
        # own so neither binding can borrow the other's site.

        development_grant_values = (
            self.mcp_atlassian_bearer_token_file,
            self.mcp_atlassian_jira_bearer_token_file,
            self.mcp_atlassian_confluence_bearer_token_file,
            self.mcp_atlassian_credentials_file,
            self.mcp_atlassian_jira_credentials_file,
            self.mcp_atlassian_confluence_credentials_file,
            self.mcp_atlassian_grant_tenant_id,
            self.mcp_atlassian_grant_user_id,
            self.mcp_figma_bearer_token_file,
            self.mcp_figma_credentials_file,
            self.mcp_figma_grant_tenant_id,
            self.mcp_figma_grant_user_id,
        )
        if self.environment == "production" and (
            self.mcp_grant_backend == "development_files"
            or any(value is not None for value in development_grant_values)
        ):
            raise ValueError("Development file grants are forbidden in production")

        if self.mcp_grant_backend == "disabled" and any(
            value is not None for value in development_grant_values
        ):
            raise ValueError(
                "Development grant bindings require PKA_MCP_GRANT_BACKEND=development_files"
            )

        if self.mcp_grant_backend == "development_files":
            if self.environment not in {"development", "test"}:
                raise ValueError("Development file grants require development or test")
            if self.mcp_atlassian_enabled:
                self._require_complete_grant_binding(
                    "Atlassian",
                    self.mcp_atlassian_bearer_token_file or self.mcp_atlassian_credentials_file,
                    self.mcp_atlassian_grant_tenant_id,
                    self.mcp_atlassian_grant_user_id,
                )
            if self.mcp_figma_enabled:
                self._require_complete_grant_binding(
                    "Figma",
                    self.mcp_figma_bearer_token_file or self.mcp_figma_credentials_file,
                    self.mcp_figma_grant_tenant_id,
                    self.mcp_figma_grant_user_id,
                )

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

    @property
    def atlassian_jira_token_file(self) -> Path | None:
        """Token file serving the Jira binding: its override, else the provider file."""
        return self.mcp_atlassian_jira_bearer_token_file or self.mcp_atlassian_bearer_token_file

    @property
    def atlassian_confluence_token_file(self) -> Path | None:
        """Token file serving the Confluence binding: its override, else the provider file."""
        return (
            self.mcp_atlassian_confluence_bearer_token_file or self.mcp_atlassian_bearer_token_file
        )

    @property
    def atlassian_jira_credentials_file(self) -> Path | None:
        """Renewable credentials serving Jira: its override, else the provider document."""
        return self.mcp_atlassian_jira_credentials_file or self.mcp_atlassian_credentials_file

    @property
    def atlassian_confluence_credentials_file(self) -> Path | None:
        """Renewable credentials serving Confluence: its override, else the provider document."""
        return self.mcp_atlassian_confluence_credentials_file or self.mcp_atlassian_credentials_file

    @staticmethod
    def _require_complete_grant_binding(
        provider_name: str,
        token_file: Path | None,
        tenant_id: str | None,
        user_id: str | None,
    ) -> None:
        if token_file is None or tenant_id is None or user_id is None:
            raise ValueError(
                f"The {provider_name} development grant requires file, tenant, and user bindings"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
