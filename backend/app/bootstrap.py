from dataclasses import dataclass

from app.approvals.adapters.memory import InMemoryActionProposalRepository
from app.approvals.workflow import ApprovalWorkflow
from app.audit.adapters.memory import InMemoryAuditSink
from app.audit.ports import AuditSink
from app.conversations.adapters.memory import InMemoryConversationRepository
from app.conversations.workflow import ConversationWorkflow
from app.core.config import Settings


@dataclass(frozen=True)
class ApplicationContainer:
    """Application composition root exposed to HTTP dependency adapters."""

    approvals: ApprovalWorkflow
    audit: AuditSink
    conversations: ConversationWorkflow
    settings: Settings


def build_container(settings: Settings) -> ApplicationContainer:
    """Wire development adapters. Production wiring will live beside this factory."""

    # TODO(PERSISTENCE): Replace process-local adapters with PostgreSQL,
    # transactions, an outbox and durable idempotency before production.
    action_repository = InMemoryActionProposalRepository()
    conversation_repository = InMemoryConversationRepository()
    audit_sink = InMemoryAuditSink()

    return ApplicationContainer(
        approvals=ApprovalWorkflow(action_repository, audit_sink),
        audit=audit_sink,
        conversations=ConversationWorkflow(conversation_repository),
        settings=settings,
    )
