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
from app.mcp.domain import MCPProvider
from app.mcp.read_workflow import MCPReadWorkflow
from app.mcp.registry import MCPToolRegistry


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
            settings.mcp_atlassian_bearer_token_file is not None
            and settings.mcp_atlassian_grant_tenant_id is not None
            and settings.mcp_atlassian_grant_user_id is not None
        ):
            bindings.append(
                DevelopmentGrantBinding(
                    provider=MCPProvider.ATLASSIAN,
                    tenant_id=settings.mcp_atlassian_grant_tenant_id,
                    user_id=settings.mcp_atlassian_grant_user_id,
                    token_file=settings.mcp_atlassian_bearer_token_file,
                )
            )
        if (
            settings.mcp_figma_bearer_token_file is not None
            and settings.mcp_figma_grant_tenant_id is not None
            and settings.mcp_figma_grant_user_id is not None
        ):
            bindings.append(
                DevelopmentGrantBinding(
                    provider=MCPProvider.FIGMA,
                    tenant_id=settings.mcp_figma_grant_tenant_id,
                    user_id=settings.mcp_figma_grant_user_id,
                    token_file=settings.mcp_figma_bearer_token_file,
                )
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
