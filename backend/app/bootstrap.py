from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine

from app.approvals.adapters.memory import InMemoryApprovalUnitOfWork
from app.approvals.adapters.postgres import PostgresApprovalUnitOfWorkFactory
from app.approvals.workflow import ApprovalWorkflow
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


@dataclass(frozen=True)
class ApplicationContainer:
    """Application services and owned infrastructure resources."""

    approvals: ApprovalWorkflow
    audit: AuditSink | None
    conversations: ConversationWorkflow
    readiness_probe: Callable[[], bool]
    settings: Settings
    engine: Engine | None = None


def build_container(settings: Settings) -> ApplicationContainer:
    if settings.repository_backend == "memory":
        conversation_repository = InMemoryConversationRepository()
        approval_uow_factory = InMemoryApprovalUnitOfWork()
        return ApplicationContainer(
            approvals=ApprovalWorkflow(approval_uow_factory, conversation_repository),
            audit=approval_uow_factory.audit,
            conversations=ConversationWorkflow(conversation_repository),
            readiness_probe=lambda: True,
            settings=settings,
        )

    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    conversation_repository = PostgresConversationRepository(session_factory)
    approval_uow_factory = PostgresApprovalUnitOfWorkFactory(session_factory)
    return ApplicationContainer(
        approvals=ApprovalWorkflow(approval_uow_factory, conversation_repository),
        audit=None,
        conversations=ConversationWorkflow(conversation_repository),
        readiness_probe=lambda: database_is_ready(engine),
        settings=settings,
        engine=engine,
    )
