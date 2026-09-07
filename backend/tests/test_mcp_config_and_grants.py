import asyncio
import json
import time
from functools import partial
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.identity import SecurityContext
from app.mcp.adapters import grants
from app.mcp.adapters.grants import (
    DevelopmentFileGrantBroker,
    DevelopmentGrantBinding,
)
from app.mcp.domain import MCPBindingKind, MCPProvider
from app.mcp.errors import MCPGrantUnavailable

JIRA_CLOUD_ID = UUID("11111111-1111-4111-8111-111111111111")
CONFLUENCE_CLOUD_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_mcp_configuration_is_default_deny() -> None:
    settings = Settings(environment="test")

    assert settings.mcp_reads_enabled is False
    assert settings.mcp_mutations_enabled is False
    assert settings.mcp_atlassian_enabled is False
    assert settings.mcp_jira_enabled is False
    assert settings.mcp_confluence_enabled is False
    assert settings.mcp_figma_enabled is False
    assert settings.mcp_grant_backend == "disabled"


# Le refus inconditionnel des mutations est leve. Ce qui le remplace n'est pas une
# absence de regle mais trois dependances reelles du chemin d'ecriture : chacune est
# ce sans quoi une ecriture s'execute quand meme, mais sans ce qui la rend rattrapable.

CLOUD = "a761589f-69b8-4373-9c30-7561c2d45a39"

POSTGRES = {
    "repository_backend": "postgres",
    "database_host": "db.exemple.invalid",
    "database_name": "projet_m2",
    "database_user": "projet_m2",
    "database_password_file": "/run/secrets/postgres_password",
    "database_port": 5432,
}


def test_mutations_require_reads() -> None:
    """La revalidation de permission juste avant une ecriture EST une lecture. Sans
    elle, on ecrit sans avoir reconfirme que la cible existe et que le mandat la
    voit encore."""

    with pytest.raises(ValidationError, match="require PKA_MCP_READS_ENABLED"):
        Settings(environment="test", mcp_mutations_enabled=True)


def test_mutations_require_durable_storage() -> None:
    """Un depot en memoire perd, au redemarrage, la seule trace disant sous quelle cle
    une ecriture est partie -- ce qu'on va precisement chercher apres une coupure."""

    with pytest.raises(ValidationError, match="require the PostgreSQL repository"):
        Settings(environment="test", mcp_mutations_enabled=True, mcp_reads_enabled=True)


def test_mutations_require_a_jira_binding_when_jira_is_enabled() -> None:
    """Sans liant, aucune ecriture Jira ne peut designer son site."""

    with pytest.raises(ValidationError, match="require PKA_MCP_ATLASSIAN_JIRA_CLOUD_ID"):
        Settings(
            environment="test",
            mcp_mutations_enabled=True,
            mcp_reads_enabled=True,
            mcp_atlassian_enabled=True,
            mcp_jira_enabled=True,
            **POSTGRES,
        )


def test_mutations_are_accepted_once_every_precondition_holds() -> None:
    """Le pendant des trois refus : la regle autorise, elle n'interdit pas par
    principe."""

    settings = Settings(
        environment="test",
        mcp_mutations_enabled=True,
        mcp_reads_enabled=True,
        mcp_atlassian_enabled=True,
        mcp_jira_enabled=True,
        mcp_atlassian_jira_cloud_id=CLOUD,
        **POSTGRES,
    )

    assert settings.mcp_mutations_enabled is True


def test_enabled_mcp_reads_require_postgres_audit_repository() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL audit repository"):
        # The backend is named rather than left to the default: an environment that
        # exports PKA_REPOSITORY_BACKEND would otherwise satisfy the rule and the
        # test would pass by accident, proving nothing.
        Settings(environment="test", mcp_reads_enabled=True, repository_backend="memory")


def test_atlassian_site_bindings_require_provider_and_cloud_ids() -> None:
    with pytest.raises(ValidationError, match="requires the Atlassian provider"):
        Settings(environment="test", mcp_jira_enabled=True)

    with pytest.raises(ValidationError, match="server-side cloud ID"):
        Settings(
            environment="test",
            mcp_atlassian_enabled=True,
            mcp_jira_enabled=True,
        )

    settings = Settings(
        environment="test",
        mcp_atlassian_enabled=True,
        mcp_jira_enabled=True,
        mcp_atlassian_jira_cloud_id=JIRA_CLOUD_ID,
    )
    assert settings.mcp_atlassian_jira_cloud_id == JIRA_CLOUD_ID

    # One Atlassian site issues a single cloud ID covering both products, so the two
    # bindings sharing a value is the ordinary single-site configuration.
    shared = Settings(
        environment="test",
        mcp_atlassian_enabled=True,
        mcp_jira_enabled=True,
        mcp_confluence_enabled=True,
        mcp_atlassian_jira_cloud_id=JIRA_CLOUD_ID,
        mcp_atlassian_confluence_cloud_id=JIRA_CLOUD_ID,
    )
    assert shared.mcp_atlassian_jira_cloud_id == shared.mcp_atlassian_confluence_cloud_id

    with pytest.raises(ValidationError, match="server-side cloud ID"):
        Settings(
            environment="test",
            mcp_atlassian_enabled=True,
            mcp_jira_enabled=True,
            mcp_confluence_enabled=True,
            mcp_atlassian_jira_cloud_id=JIRA_CLOUD_ID,
        )

    distinct = Settings(
        environment="test",
        mcp_atlassian_enabled=True,
        mcp_jira_enabled=True,
        mcp_confluence_enabled=True,
        mcp_atlassian_jira_cloud_id=JIRA_CLOUD_ID,
        mcp_atlassian_confluence_cloud_id=CONFLUENCE_CLOUD_ID,
    )
    assert distinct.mcp_atlassian_confluence_cloud_id == CONFLUENCE_CLOUD_ID


def test_development_file_grant_requires_complete_explicit_binding(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="requires file, tenant, and user"):
        Settings(
            environment="test",
            mcp_grant_backend="development_files",
            mcp_figma_enabled=True,
            mcp_figma_bearer_token_file=tmp_path / "figma-token",
        )

    with pytest.raises(ValidationError, match="require PKA_MCP_GRANT_BACKEND"):
        Settings(
            environment="test",
            mcp_figma_bearer_token_file=tmp_path / "figma-token",
        )


def test_development_grant_broker_refuses_non_development_environment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="forbidden"):
        DevelopmentFileGrantBroker(
            environment="production",
            bindings=(
                DevelopmentGrantBinding(
                    provider=MCPProvider.FIGMA,
                    binding=MCPBindingKind.FIGMA,
                    tenant_id="tenant-a",
                    user_id="user-a",
                    token_file=tmp_path / "figma-token",
                ),
            ),
        )


def test_grants_are_isolated_by_provider_tenant_and_user(tmp_path: Path) -> None:
    figma_token = "figma-synthetic-token-0001"
    atlassian_token = "atlassian-synthetic-token-0002"
    figma_file = tmp_path / "figma-token"
    atlassian_file = tmp_path / "atlassian-token"
    figma_file.write_text(figma_token + "\n", encoding="ascii")
    atlassian_file.write_text(atlassian_token + "\n", encoding="ascii")
    broker = DevelopmentFileGrantBroker(
        environment="test",
        bindings=(
            DevelopmentGrantBinding(
                provider=MCPProvider.FIGMA,
                binding=MCPBindingKind.FIGMA,
                tenant_id="tenant-a",
                user_id="user-a",
                token_file=figma_file,
            ),
            DevelopmentGrantBinding(
                provider=MCPProvider.ATLASSIAN,
                binding=MCPBindingKind.JIRA,
                tenant_id="tenant-b",
                user_id="user-b",
                token_file=atlassian_file,
            ),
        ),
    )

    grant = asyncio.run(
        broker.acquire(
            provider=MCPProvider.FIGMA,
            binding=MCPBindingKind.FIGMA,
            context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
        )
    )
    assert grant.provider == MCPProvider.FIGMA
    assert grant.access_token == figma_token
    assert figma_token not in repr(grant)
    assert atlassian_token not in repr(grant)

    for context in (
        SecurityContext(tenant_id="tenant-b", user_id="user-a"),
        SecurityContext(tenant_id="tenant-a", user_id="user-b"),
    ):
        with pytest.raises(MCPGrantUnavailable):
            asyncio.run(
                broker.acquire(
                    provider=MCPProvider.FIGMA,
                    binding=MCPBindingKind.FIGMA,
                    context=context,
                )
            )

    with pytest.raises(MCPGrantUnavailable):
        asyncio.run(
            broker.acquire(
                provider=MCPProvider.ATLASSIAN,
                binding=MCPBindingKind.JIRA,
                context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
            )
        )


def test_each_atlassian_binding_receives_its_own_site_token(tmp_path: Path) -> None:
    """A delegated token covers one site, so Jira and Confluence must not share one."""

    jira_file = tmp_path / "jira-token"
    confluence_file = tmp_path / "confluence-token"
    jira_file.write_text("jira-site-synthetic-token-0001\n", encoding="ascii")
    confluence_file.write_text("confluence-site-synthetic-token-0002\n", encoding="ascii")
    broker = DevelopmentFileGrantBroker(
        environment="test",
        bindings=(
            DevelopmentGrantBinding(
                provider=MCPProvider.ATLASSIAN,
                binding=MCPBindingKind.JIRA,
                tenant_id="tenant-a",
                user_id="user-a",
                token_file=jira_file,
            ),
            DevelopmentGrantBinding(
                provider=MCPProvider.ATLASSIAN,
                binding=MCPBindingKind.CONFLUENCE,
                tenant_id="tenant-a",
                user_id="user-a",
                token_file=confluence_file,
            ),
        ),
    )
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")

    def token_for(binding: MCPBindingKind) -> str:
        grant = asyncio.run(
            broker.acquire(provider=MCPProvider.ATLASSIAN, binding=binding, context=context)
        )
        return grant.access_token

    assert token_for(MCPBindingKind.JIRA) == "jira-site-synthetic-token-0001"
    assert token_for(MCPBindingKind.CONFLUENCE) == "confluence-site-synthetic-token-0002"
    # An unregistered binding must not silently borrow a sibling's token: doing so
    # would send a site's credential to a server call scoped to a different site.
    with pytest.raises(MCPGrantUnavailable):
        token_for(MCPBindingKind.NONE)


def test_same_provider_cannot_register_a_binding_twice(tmp_path: Path) -> None:
    duplicate = DevelopmentGrantBinding(
        provider=MCPProvider.ATLASSIAN,
        binding=MCPBindingKind.JIRA,
        tenant_id="tenant-a",
        user_id="user-a",
        token_file=tmp_path / "jira-token",
    )
    with pytest.raises(ValueError, match="per binding kind"):
        DevelopmentFileGrantBroker(environment="test", bindings=(duplicate, duplicate))


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx2 so the renewal path is exercised without a network."""

    def __init__(
        self, recorder: list[dict[str, str]], response: _FakeResponse, **_: object
    ) -> None:
        self._recorder = recorder
        self._response = response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(
        self, url: str, *, data: dict[str, str], headers: dict[str, str]
    ) -> _FakeResponse:
        del headers
        self._recorder.append({"url": url, **data})
        return self._response


def _credentials_broker(path: Path) -> DevelopmentFileGrantBroker:
    return DevelopmentFileGrantBroker(
        environment="test",
        bindings=(
            DevelopmentGrantBinding(
                provider=MCPProvider.ATLASSIAN,
                binding=MCPBindingKind.JIRA,
                tenant_id="tenant-a",
                user_id="user-a",
                credentials_file=path,
                token_endpoint="https://cf.example.invalid/v1/token",
            ),
        ),
    )


def _acquire(broker: DevelopmentFileGrantBroker) -> str:
    grant = asyncio.run(
        broker.acquire(
            provider=MCPProvider.ATLASSIAN,
            binding=MCPBindingKind.JIRA,
            context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
        )
    )
    return grant.access_token


def test_a_grant_binding_needs_exactly_one_source(tmp_path: Path) -> None:
    common = {
        "provider": MCPProvider.ATLASSIAN,
        "binding": MCPBindingKind.JIRA,
        "tenant_id": "tenant-a",
        "user_id": "user-a",
    }
    with pytest.raises(ValueError, match="exactly one"):
        DevelopmentGrantBinding(**common)
    with pytest.raises(ValueError, match="exactly one"):
        DevelopmentGrantBinding(
            **common,
            token_file=tmp_path / "token",
            credentials_file=tmp_path / "credentials.json",
        )
    # An https endpoint is mandatory: the refresh token is posted to it, so a
    # cleartext or missing endpoint would hand the long-lived grant to the network.
    with pytest.raises(ValueError, match="token endpoint"):
        DevelopmentGrantBinding(**common, credentials_file=tmp_path / "credentials.json")
    with pytest.raises(ValueError, match="must be https"):
        DevelopmentGrantBinding(
            **common,
            credentials_file=tmp_path / "credentials.json",
            token_endpoint="http://cf.example.invalid/v1/token",
        )


def test_a_valid_credential_is_served_without_contacting_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token with life left must not trigger an exchange, or every read pays for one."""

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "still-valid-synthetic-token",
                "refresh_token": "synthetic-refresh-0001",
                "client_id": "synthetic-client",
                "expires_at": time.time() + 3600,
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        grants.httpx2,
        "AsyncClient",
        partial(_FakeAsyncClient, calls, _FakeResponse(200, {})),
    )

    assert _acquire(_credentials_broker(path)) == "still-valid-synthetic-token"
    assert calls == []


def test_an_expired_credential_is_renewed_and_the_rotated_refresh_token_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atlassian rotates the refresh token, so losing it would strand the deployment."""

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "expired-synthetic-token",
                "refresh_token": "synthetic-refresh-0001",
                "client_id": "synthetic-client",
                "expires_at": time.time() - 1,
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        grants.httpx2,
        "AsyncClient",
        partial(
            _FakeAsyncClient,
            calls,
            _FakeResponse(
                200,
                {
                    "access_token": "renewed-synthetic-token",
                    "refresh_token": "synthetic-refresh-0002",
                    "expires_in": 28320,
                },
            ),
        ),
    )
    broker = _credentials_broker(path)

    assert _acquire(broker) == "renewed-synthetic-token"
    assert calls == [
        {
            "url": "https://cf.example.invalid/v1/token",
            "grant_type": "refresh_token",
            "refresh_token": "synthetic-refresh-0001",
            "client_id": "synthetic-client",
        }
    ]

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["access_token"] == "renewed-synthetic-token"
    assert persisted["refresh_token"] == "synthetic-refresh-0002"
    assert persisted["expires_at"] > time.time()
    # The renewal is durable: a second read is served from the file, not re-exchanged.
    assert _acquire(broker) == "renewed-synthetic-token"
    assert len(calls) == 1


def test_a_client_secret_is_sent_when_the_provider_is_not_a_public_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Figma advertises only client_secret_* auth, so omitting the secret is refused."""

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "expired-synthetic-token",
                "refresh_token": "synthetic-refresh-0001",
                "client_id": "synthetic-client",
                "client_secret": "synthetic-secret-0001",
                "expires_at": 0.0,
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        grants.httpx2,
        "AsyncClient",
        partial(
            _FakeAsyncClient,
            calls,
            _FakeResponse(200, {"access_token": "renewed-synthetic-token", "expires_in": 3600}),
        ),
    )
    broker = DevelopmentFileGrantBroker(
        environment="test",
        bindings=(
            DevelopmentGrantBinding(
                provider=MCPProvider.FIGMA,
                binding=MCPBindingKind.FIGMA,
                tenant_id="tenant-a",
                user_id="user-a",
                credentials_file=path,
                token_endpoint="https://api.example.invalid/v1/oauth/token",
            ),
        ),
    )

    grant = asyncio.run(
        broker.acquire(
            provider=MCPProvider.FIGMA,
            binding=MCPBindingKind.FIGMA,
            context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
        )
    )
    assert grant.access_token == "renewed-synthetic-token"
    assert calls[0]["client_secret"] == "synthetic-secret-0001"
    # A rotation that returns no refresh token must keep the one already held,
    # otherwise the next renewal has nothing to present.
    assert json.loads(path.read_text(encoding="utf-8"))["refresh_token"] == "synthetic-refresh-0001"


def test_a_public_client_document_sends_no_client_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atlassian registers a public client; sending an empty secret would be rejected."""

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "expired-synthetic-token",
                "refresh_token": "synthetic-refresh-0001",
                "client_id": "synthetic-client",
                "expires_at": 0.0,
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        grants.httpx2,
        "AsyncClient",
        partial(
            _FakeAsyncClient,
            calls,
            _FakeResponse(200, {"access_token": "renewed-synthetic-token", "expires_in": 3600}),
        ),
    )

    _acquire(_credentials_broker(path))
    assert "client_secret" not in calls[0]


def test_a_refused_renewal_surfaces_as_an_unavailable_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revoked refresh token is a grant problem, and the response body never leaks."""

    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "expired-synthetic-token",
                "refresh_token": "synthetic-refresh-0001",
                "client_id": "synthetic-client",
                "expires_at": 0.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        grants.httpx2,
        "AsyncClient",
        partial(
            _FakeAsyncClient,
            [],
            _FakeResponse(400, {"error": "invalid_grant", "refresh_token": "leaked-0001"}),
        ),
    )

    with pytest.raises(MCPGrantUnavailable) as caught:
        _acquire(_credentials_broker(path))
    assert "leaked-0001" not in str(caught.value)
    # The document is left untouched, so a transient refusal cannot destroy the grant.
    assert json.loads(path.read_text(encoding="utf-8"))["refresh_token"] == "synthetic-refresh-0001"


def test_missing_or_invalid_secret_file_has_expurgated_error(tmp_path: Path) -> None:
    missing = tmp_path / "never-log-this-path-or-token"
    broker = DevelopmentFileGrantBroker(
        environment="test",
        bindings=(
            DevelopmentGrantBinding(
                provider=MCPProvider.FIGMA,
                binding=MCPBindingKind.FIGMA,
                tenant_id="tenant-a",
                user_id="user-a",
                token_file=missing,
            ),
        ),
    )

    with pytest.raises(MCPGrantUnavailable) as caught:
        asyncio.run(
            broker.acquire(
                provider=MCPProvider.FIGMA,
                binding=MCPBindingKind.FIGMA,
                context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
            )
        )

    assert str(missing) not in str(caught.value)


def test_grant_is_reread_instead_of_persisted(tmp_path: Path) -> None:
    token_file = tmp_path / "rotating-token"
    token_file.write_text("synthetic-token-version-one\n", encoding="ascii")
    broker = DevelopmentFileGrantBroker(
        environment="test",
        bindings=(
            DevelopmentGrantBinding(
                provider=MCPProvider.FIGMA,
                binding=MCPBindingKind.FIGMA,
                tenant_id="tenant-a",
                user_id="user-a",
                token_file=token_file,
            ),
        ),
    )
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")

    acquire = partial(
        broker.acquire,
        provider=MCPProvider.FIGMA,
        binding=MCPBindingKind.FIGMA,
        context=context,
    )
    first = asyncio.run(acquire())
    token_file.write_text("synthetic-token-version-two\n", encoding="ascii")
    second = asyncio.run(acquire())

    assert first.access_token == "synthetic-token-version-one"
    assert second.access_token == "synthetic-token-version-two"
