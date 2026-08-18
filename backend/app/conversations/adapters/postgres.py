from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.conversations.domain import Conversation, ConversationMessage
from app.persistence.errors import PersistenceMappingError
from app.persistence.schema import (
    conversation_messages,
    conversations,
    message_sources,
)


class PostgresConversationRepository:
    """SQLAlchemy adapter opening a fresh Session for every repository call."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, conversation: Conversation) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                insert(conversations).values(
                    tenant_id=conversation.tenant_id,
                    id=conversation.id,
                    owner_user_id=conversation.owner_user_id,
                    title=conversation.title,
                    created_at=conversation.created_at,
                )
            )

    def get(self, *, tenant_id: str, conversation_id: UUID) -> Conversation | None:
        statement = select(conversations).where(
            conversations.c.tenant_id == tenant_id,
            conversations.c.id == conversation_id,
        )
        with self._session_factory() as session:
            row = session.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        try:
            return Conversation.model_validate(dict(row))
        except ValidationError:
            raise PersistenceMappingError("Stored conversation is invalid") from None


class PostgresConversationMessageRepository:
    """Durable turns, written as one transaction per exchange turn."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(self, message: ConversationMessage) -> None:
        # One transaction for the turn and its citations: an answer whose sources
        # were lost would look like an answer that cited nothing, which is a
        # different and worse claim than an answer that was never stored.
        with self._session_factory.begin() as session:
            # Read and assign inside the same transaction. Two concurrent turns in
            # one thread then collide on the unique constraint instead of silently
            # taking the same rank, which is the failure we want: loud, not subtle.
            taken = session.execute(
                select(func.max(conversation_messages.c.sequence)).where(
                    conversation_messages.c.tenant_id == message.tenant_id,
                    conversation_messages.c.conversation_id == message.conversation_id,
                )
            ).scalar()
            session.execute(
                insert(conversation_messages).values(
                    tenant_id=message.tenant_id,
                    id=message.id,
                    conversation_id=message.conversation_id,
                    author_user_id=message.author_user_id,
                    sequence=0 if taken is None else taken + 1,
                    role=message.role.value,
                    content=message.content,
                    correlation_id=message.correlation_id,
                    status=message.status.value,
                    created_at=message.created_at,
                )
            )
            if not message.sources:
                return
            session.execute(
                insert(message_sources),
                [
                    {
                        "tenant_id": message.tenant_id,
                        "id": uuid4(),
                        "message_id": message.id,
                        "position": position,
                        "source_system": source.source_system,
                        "tool_name": source.tool_name,
                        "resource_reference": source.resource_reference,
                        "retrieved_at": source.retrieved_at,
                        "truncated": source.truncated,
                    }
                    for position, source in enumerate(message.sources)
                ],
            )

    def list_for_conversation(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        limit: int,
    ) -> tuple[ConversationMessage, ...]:
        # Newest first here, reversed below: the cap has to keep the most recent
        # turns, and only the database can decide that before the rows are read.
        # Ranked by sequence, never by timestamp -- see the column's comment.
        turns = (
            select(conversation_messages)
            .where(
                conversation_messages.c.tenant_id == tenant_id,
                conversation_messages.c.conversation_id == conversation_id,
            )
            .order_by(conversation_messages.c.sequence.desc())
            .limit(limit)
        )
        with self._session_factory() as session:
            rows = [dict(row) for row in session.execute(turns).mappings()]
            if not rows:
                return ()
            cited = (
                select(message_sources)
                .where(
                    message_sources.c.tenant_id == tenant_id,
                    message_sources.c.message_id.in_([row["id"] for row in rows]),
                )
                .order_by(message_sources.c.position)
            )
            sources: dict[UUID, list[dict[str, object]]] = {}
            for source in session.execute(cited).mappings():
                sources.setdefault(source["message_id"], []).append(dict(source))

        rows.reverse()
        try:
            return tuple(
                ConversationMessage.model_validate(
                    {**row, "sources": sources.get(row["id"], [])}
                )
                for row in rows
            )
        except ValidationError:
            raise PersistenceMappingError("Stored conversation turn is invalid") from None
