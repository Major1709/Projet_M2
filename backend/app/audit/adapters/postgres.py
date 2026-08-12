from sqlalchemy import insert
from sqlalchemy.orm import Session, sessionmaker

from app.audit.domain import AuditEvent
from app.persistence.schema import audit_events


class PostgresAuditSink:
    """Appends audit events through the approval transaction's Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: AuditEvent) -> None:
        self._session.execute(
            insert(audit_events).values(
                tenant_id=event.tenant_id,
                id=event.id,
                event_type=event.event_type.value,
                actor_user_id=event.actor_user_id,
                correlation_id=event.correlation_id,
                action_proposal_id=event.action_proposal_id,
                details=event.model_dump(mode="json")["details"],
                occurred_at=event.occurred_at,
            )
        )


class PostgresAppendOnlyAuditWriter:
    """Persists one event per short autonomous transaction, never around I/O."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(self, event: AuditEvent) -> None:
        with self._session_factory.begin() as session:
            PostgresAuditSink(session).append(event)
