from threading import RLock
from uuid import UUID

from app.conversations.domain import Conversation


class InMemoryConversationRepository:
    """Development-only, process-local repository."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, UUID], Conversation] = {}
        self._lock = RLock()

    def add(self, conversation: Conversation) -> None:
        with self._lock:
            self._items[(conversation.tenant_id, conversation.id)] = conversation

    def get(self, *, tenant_id: str, conversation_id: UUID) -> Conversation | None:
        with self._lock:
            return self._items.get((tenant_id, conversation_id))
