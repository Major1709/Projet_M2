import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.identity import SecurityContext
from app.mcp.adapters.grants import (
    DevelopmentFileGrantBroker,
    DevelopmentGrantBinding,
)
from app.mcp.domain import MCPProvider
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


def test_mcp_mutations_cannot_be_enabled() -> None:
    with pytest.raises(ValidationError, match="MCP mutations cannot be enabled"):
        Settings(environment="test", mcp_mutations_enabled=True)


def test_enabled_mcp_reads_require_postgres_audit_repository() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL audit repository"):
        Settings(environment="test", mcp_reads_enabled=True)


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

    with pytest.raises(ValidationError, match="distinct cloud IDs"):
        Settings(
            environment="test",
            mcp_atlassian_enabled=True,
            mcp_jira_enabled=True,
            mcp_confluence_enabled=True,
            mcp_atlassian_jira_cloud_id=JIRA_CLOUD_ID,
            mcp_atlassian_confluence_cloud_id=JIRA_CLOUD_ID,
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
                tenant_id="tenant-a",
                user_id="user-a",
                token_file=figma_file,
            ),
            DevelopmentGrantBinding(
                provider=MCPProvider.ATLASSIAN,
                tenant_id="tenant-b",
                user_id="user-b",
                token_file=atlassian_file,
            ),
        ),
    )

    grant = asyncio.run(
        broker.acquire(
            provider=MCPProvider.FIGMA,
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
            asyncio.run(broker.acquire(provider=MCPProvider.FIGMA, context=context))

    with pytest.raises(MCPGrantUnavailable):
        asyncio.run(
            broker.acquire(
                provider=MCPProvider.ATLASSIAN,
                context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
            )
        )


def test_missing_or_invalid_secret_file_has_expurgated_error(tmp_path: Path) -> None:
    missing = tmp_path / "never-log-this-path-or-token"
    broker = DevelopmentFileGrantBroker(
        environment="test",
        bindings=(
            DevelopmentGrantBinding(
                provider=MCPProvider.FIGMA,
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
                tenant_id="tenant-a",
                user_id="user-a",
                token_file=token_file,
            ),
        ),
    )
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")

    first = asyncio.run(broker.acquire(provider=MCPProvider.FIGMA, context=context))
    token_file.write_text("synthetic-token-version-two\n", encoding="ascii")
    second = asyncio.run(broker.acquire(provider=MCPProvider.FIGMA, context=context))

    assert first.access_token == "synthetic-token-version-one"
    assert second.access_token == "synthetic-token-version-two"
