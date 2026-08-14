from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine

from app.approvals.adapters.memory import InMemoryApprovalUnitOfWork
from app.approvals.adapters.postgres import PostgresApprovalUnitOfWorkFactory
from app.approvals.workflow import ApprovalWorkflow
from app.audit.adapters.postgres import PostgresAppendOnlyAuditWriter
from app.audit.ports import AuditSink
from app.conversations.adapters.memory import InMemoryConversationRepository
from app.conversations.adapters.postgres import PostgresConversationRepository
from app.conversations.workflow import ConversationWorkflow
from app.core.config import Settings
from app.core.database import (
    create_database_engine,
    create_session_factory,
    database_is_ready,
)
from app.mcp.adapters.grants import (
    DevelopmentFileGrantBroker,
    DevelopmentGrantBinding,
    UnavailableGrantBroker,
)
from app.mcp.adapters.remote import SDKRemoteMCPTransport
from app.mcp.domain import MCPBindingKind, MCPProvider
from app.mcp.read_workflow import MCPReadWorkflow
from app.mcp.registry import ATLASSIAN_TOKEN_ENDPOINT, MCPToolRegistry


@dataclass(frozen=True)
class ApplicationContainer:
    """Application services and owned infrastructure resources."""

    approvals: ApprovalWorkflow
    audit: AuditSink | None
    conversations: ConversationWorkflow
    mcp_reads: MCPReadWorkflow
    readiness_probe: Callable[[], bool]
    settings: Settings
    engine: Engine | None = None


def build_container(settings: Settings) -> ApplicationContainer:
    if settings.repository_backend == "memory":
        conversation_repository = InMemoryConversationRepository()
        approval_uow_factory = InMemoryApprovalUnitOfWork()
        mcp_reads = _build_mcp_read_workflow(settings, approval_uow_factory.audit)
        return ApplicationContainer(
            approvals=ApprovalWorkflow(approval_uow_factory, conversation_repository),
            audit=approval_uow_factory.audit,
            conversations=ConversationWorkflow(conversation_repository),
            mcp_reads=mcp_reads,
            readiness_probe=lambda: True,
            settings=settings,
        )

    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    conversation_repository = PostgresConversationRepository(session_factory)
    approval_uow_factory = PostgresApprovalUnitOfWorkFactory(session_factory)
    audit_writer = PostgresAppendOnlyAuditWriter(session_factory)
    mcp_reads = _build_mcp_read_workflow(settings, audit_writer)
    return ApplicationContainer(
        approvals=ApprovalWorkflow(approval_uow_factory, conversation_repository),
        audit=audit_writer,
        conversations=ConversationWorkflow(conversation_repository),
        mcp_reads=mcp_reads,
        readiness_probe=lambda: database_is_ready(engine),
        settings=settings,
        engine=engine,
    )


def _build_mcp_read_workflow(settings: Settings, audit_sink: AuditSink) -> MCPReadWorkflow:
    if settings.mcp_grant_backend == "development_files":
        bindings: list[DevelopmentGrantBinding] = []
        if (
            settings.mcp_atlassian_grant_tenant_id is not None
            and settings.mcp_atlassian_grant_user_id is not None
        ):
            # One entry per binding kind: a delegated token covers a single site, so
            # Jira and Confluence get their own grant when they live on separate sites
            # and fall back to the provider-wide one otherwise. The mapping is fixed
            # here at startup, so the broker never has to guess at call time.
            #
            # Each pairs a renewable credentials document with a static token file.
            # The document wins where both are configured: it can refresh itself,
            # while the plain file expires into a manual re-authorisation.
            atlassian_grants = {
                MCPBindingKind.NONE: (
                    settings.mcp_atlassian_credentials_file,
                    settings.mcp_atlassian_bearer_token_file,
                ),
                MCPBindingKind.JIRA: (
                    settings.atlassian_jira_credentials_file,
                    settings.atlassian_jira_token_file,
                ),
                MCPBindingKind.CONFLUENCE: (
                    settings.atlassian_confluence_credentials_file,
                    settings.atlassian_confluence_token_file,
                ),
            }
            bindings.extend(
                DevelopmentGrantBinding(
                    provider=MCPProvider.ATLASSIAN,
                    binding=binding_kind,
                    tenant_id=settings.mcp_atlassian_grant_tenant_id,
                    user_id=settings.mcp_atlassian_grant_user_id,
                    credentials_file=credentials_file,
                    token_endpoint=ATLASSIAN_TOKEN_ENDPOINT if credentials_file else None,
                    token_file=None if credentials_file else token_file,
                )
                for binding_kind, (credentials_file, token_file) in atlassian_grants.items()
                if credentials_file is not None or token_file is not None
            )
        if (
            settings.mcp_figma_bearer_token_file is not None
            and settings.mcp_figma_grant_tenant_id is not None
            and settings.mcp_figma_grant_user_id is not None
        ):
            # whoami is site-independent and carries NONE; the others carry FIGMA.
            # A single file serves both, but each is registered on its own key.
            bindings.extend(
                DevelopmentGrantBinding(
                    provider=MCPProvider.FIGMA,
                    binding=binding_kind,
                    tenant_id=settings.mcp_figma_grant_tenant_id,
                    user_id=settings.mcp_figma_grant_user_id,
                    token_file=settings.mcp_figma_bearer_token_file,
                )
                for binding_kind in (MCPBindingKind.NONE, MCPBindingKind.FIGMA)
            )
        grant_broker = DevelopmentFileGrantBroker(
            environment=settings.environment,
            bindings=tuple(bindings),
        )
    else:
        grant_broker = UnavailableGrantBroker()

    return MCPReadWorkflow(
        settings=settings,
        registry=MCPToolRegistry(),
        transport=SDKRemoteMCPTransport(grant_broker=grant_broker),
        audit_sink=audit_sink,
    )
