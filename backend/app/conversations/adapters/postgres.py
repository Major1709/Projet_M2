from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.conversations.domain import Conversation
from app.persistence.errors import PersistenceMappingError
from app.persistence.schema import conversations


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
