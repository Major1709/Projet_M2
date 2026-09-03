import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_loopback(hostname: str | None) -> bool:
    """True only for the local machine, by name or by address.

    ``localhost`` is compared exactly rather than by prefix: ``localhost.evil.test``
    starts with it, resolves wherever its owner points it, and would otherwise have
    passed as local -- carrying an authorization code to a third party over plain
    HTTP.
    """

    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname.strip("[]")).is_loopback
    except ValueError:
        return False


def _validate_redirect_uri(redirect: str, *, environment: str) -> None:
    """HTTPS everywhere, with one narrow exception for a developer machine.

    An authorization code travelling over plain HTTP is a code anyone on the path
    can redeem, so the exception is fenced on both sides: the environment has to be
    ``development`` **and** the host has to be the local machine. Either alone is not
    enough.
    """

    parsed = urlsplit(redirect)
    if parsed.scheme == "https":
        return
    if parsed.scheme != "http":
        raise ValueError("The Atlassian redirect URI must use HTTPS")
    if environment != "development":
        raise ValueError(
            "A plain HTTP redirect URI is only allowed in the development environment"
        )
    if not _is_loopback(parsed.hostname):
        raise ValueError("A plain HTTP redirect URI is only allowed on the loopback host")


def _validate_post_login_target(target: str, *, allowed_origins: tuple[str, ...]) -> None:
    """A same-origin path, or an absolute URL at an origin already trusted for CORS.

    The path rules are unchanged and remain the common case. ``//elsewhere.example``
    starts with a slash and is a protocol-relative URL that browsers follow off-site,
    so the leading-slash check alone leaves open the redirect it was meant to close,
    and a backslash is folded to a slash by some browsers, which reopens it a second
    way.

    An absolute URL is admitted only when its origin is one the deployment already
    names in ``frontend_origins``. That adds no new trust: the list is the
    deployment's own statement of which browser origins may call it, and reusing it
    here means a front end on another port stops being unreachable after sign-in
    without the redirect ever becoming aimable. An origin absent from the list is
    refused, so an edited environment file cannot turn this into an open redirect on
    its own.

    Matching is exact, so a difference of case or a trailing slash is a refusal
    rather than a guess. Fail-closed is the right direction here: the cost is an
    error at startup, and the alternative cost is a redirect somebody else chose.
    """

    if target.startswith("/"):
        if target.startswith(("//", "/\\")):
            raise ValueError("The post sign-in target must not be a protocol-relative URL")
        return

    parsed = urlsplit(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            "The post sign-in target must be a path or an absolute http(s) URL"
        )
    # Rebuilt from the parsed parts rather than sliced from the string, so a
    # userinfo section -- http://localhost:3000@elsewhere.example -- is compared as
    # the origin a browser would actually navigate to.
    if f"{parsed.scheme}://{parsed.netloc}" not in allowed_origins:
        raise ValueError(
            "An absolute post sign-in target must be one of the configured frontend origins"
        )


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
    # Two modes now. ``dev_headers`` remains the default so an existing front end
    # keeps working; ``session`` is what a deployment switches to once a sign-in
    # flow exists, and it makes the identity headers inert.
    auth_mode: Literal["dev_headers", "session"] = "dev_headers"
    session_lifetime_hours: int = Field(default=12, ge=1, le=24 * 30)

    # Seals the delegated grants at rest. 32 bytes in hexadecimal, in a file --
    # never an environment variable, which every child process inherits and every
    # crash reporter collects. Absent, the durable grant store is not built and
    # consent stays in process memory, which is the safer of the two omissions.
    token_encryption_key_file: Path | None = None

    # Semantic retrieval. Off by default: the runtime weighs about 2,3 Go and
    # downloads a model on first use, so a deployment must ask for it rather than
    # acquire it by upgrading.
    embeddings_enabled: bool = False
    embedding_model: str = Field(default="intfloat/multilingual-e5-base", min_length=1)
    # How many leads a question is offered. Prepended to every step's transcript,
    # so each extra one is paid for again at every turn.
    retrieval_limit: int = Field(default=5, ge=1, le=20)
    # The JQL the reindex route walks. A setting rather than a request field: a
    # caller who chooses the query chooses what enters the tenant's index.
    reindex_jql: str = Field(default="ORDER BY created DESC", min_length=1, max_length=4_000)

    # Atlassian 3LO. Off by default: a deployment that has not registered an OAuth
    # app must not expose a sign-in route that can only fail.
    atlassian_oauth_enabled: bool = False
    atlassian_oauth_client_id: str | None = Field(default=None, min_length=1, max_length=200)
    atlassian_oauth_client_secret_file: Path | None = None
    # Must match the app registration exactly. Not derived from the request, because
    # a redirect target taken from a Host header is a redirect an attacker can aim.
    atlassian_oauth_redirect_uri: str | None = Field(default=None, min_length=1, max_length=500)
    # Where the browser lands once signed in. Never a caller-supplied "next" -- an
    # open redirect is the classic hole in this flow. A path stays the common case;
    # an absolute URL is accepted only at an origin already listed in
    # PKA_FRONTEND_ORIGINS, which is what lets a front end served from another port
    # be returned to. The field keeps its "path" name so deployments that set
    # PKA_ATLASSIAN_OAUTH_POST_LOGIN_PATH keep working unchanged.
    atlassian_oauth_post_login_path: str = Field(default="/", min_length=1, max_length=200)
    # Pins which site becomes the tenant when a grant covers several. Absent, a
    # multi-site grant is refused rather than resolved by picking one.
    atlassian_expected_cloud_id: str | None = Field(default=None, min_length=1, max_length=200)
    # Browser origins allowed to call the API cross-origin. Empty by default, which
    # installs no CORS middleware at all: a browser then refuses the call, which is
    # the right answer for a deployment that has not named its front end.
    #
    # Exact origins only -- no wildcard, no regex. The identity headers this API
    # trusts are chosen by the caller, so an origin that can send them can pick a
    # tenant, and "*" would hand that to any page the browser happens to load.
    frontend_origins: tuple[str, ...] = ()
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
    # How long an approval stays spendable. Short on purpose: the human approved what
    # was on screen, and the further the target drifts from that moment the less the
    # approval means. Fifteen minutes covers a read-check-approve round trip.
    approval_ttl_seconds: int = Field(default=900, ge=60, le=3_600)
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
    # The Groq endpoint is fixed in the adapter, not declared here. A destination
    # that configuration could move is a destination an operator error -- or an
    # edited environment file -- can point elsewhere, carrying the API key with it.
    llm_groq_enabled: bool = False
    llm_groq_model: str = Field(default="qwen/qwen3.6-27b", min_length=1, max_length=200)
    llm_groq_api_key_file: Path | None = None
    # Bounded by the model's own completion ceiling so no configuration can raise it
    # past what the provider will actually produce.
    llm_groq_max_completion_tokens: int = Field(default=16_384, ge=256, le=16_384)
    # Gemini sits beside Groq rather than replacing it, and that is deliberate: the
    # way back from a provider that disappoints is then a boolean, not a redeploy of
    # a configuration nobody wrote down. Exactly one may be enabled at a time -- see
    # the check below, which refuses the ambiguity instead of picking a winner.
    llm_gemini_enabled: bool = False
    llm_gemini_model: str = Field(default="gemini-3.5-flash-lite", min_length=1, max_length=200)
    llm_gemini_api_key_file: Path | None = None
    # Lower than Groq's, and bounded by the adapter's own conservative ceiling: the
    # flash-lite output limit has not been measured here, so configuration is not
    # allowed to assert one.
    llm_gemini_max_completion_tokens: int = Field(default=8_192, ge=256, le=8_192)

    @field_validator(
        "atlassian_oauth_client_id",
        "atlassian_oauth_redirect_uri",
        "atlassian_expected_cloud_id",
        mode="before",
    )
    @classmethod
    def _empty_means_absent(cls, value: object) -> object:
        """An empty string is how a container says "not set", so read it that way.

        Compose substitutes a variable it cannot resolve with an empty string
        rather than dropping it. Rejecting that string is technically right and
        practically wrong: it stops the whole process over an optional pin nobody
        asked for, and the traceback names a validation rule rather than the
        variable. Absent and empty mean the same thing here, so they behave the
        same. What must never be silently accepted is a *wrong* value, and that is
        still refused -- an unmatched cloud id raises rather than resolving.
        """

        if isinstance(value, str) and not value.strip():
            return None
        return value

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

        if self.atlassian_oauth_enabled:
            missing = [
                name
                for name, value in (
                    ("client id", self.atlassian_oauth_client_id),
                    ("client secret file", self.atlassian_oauth_client_secret_file),
                    ("redirect URI", self.atlassian_oauth_redirect_uri),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "Atlassian sign-in requires its " + ", ".join(missing)
                )
            _validate_redirect_uri(
                str(self.atlassian_oauth_redirect_uri),
                environment=self.environment,
            )
            _validate_post_login_target(
                self.atlassian_oauth_post_login_path,
                allowed_origins=self.frontend_origins,
            )

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

        if self.llm_groq_enabled and self.llm_groq_api_key_file is None:
            raise ValueError("The Groq provider requires PKA_LLM_GROQ_API_KEY_FILE")

        if self.llm_gemini_enabled and self.llm_gemini_api_key_file is None:
            raise ValueError("The Gemini provider requires PKA_LLM_GEMINI_API_KEY_FILE")

        # Refused rather than resolved by precedence. A silent winner is how an
        # operator ends up reading one provider's dashboard while the other answers
        # the questions, and the switch this setting exists for is precisely the
        # moment both flags are most likely to be true at once.
        if self.llm_groq_enabled and self.llm_gemini_enabled:
            raise ValueError(
                "Enable exactly one model provider: PKA_LLM_GROQ_ENABLED and "
                "PKA_LLM_GEMINI_ENABLED are both true"
            )

        for origin in self.frontend_origins:
            parsed = urlsplit(origin)
            if (
                origin != f"{parsed.scheme}://{parsed.netloc}"
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
            ):
                raise ValueError(f"A frontend origin must be scheme://host[:port], got: {origin}")
            # Plain HTTP is tolerated only for a developer's own machine: elsewhere
            # it invites the browser to send the identity headers in clear.
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError(f"A non-local frontend origin must use HTTPS: {origin}")
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
