from collections import defaultdict
from threading import RLock
from uuid import UUID

from app.conversations.domain import Conversation, ConversationMessage


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


class InMemoryConversationMessageRepository:
    """Development-only, process-local turn store."""

    def __init__(self) -> None:
        self._items: list[ConversationMessage] = []
        self._next: defaultdict[tuple[str, UUID], int] = defaultdict(int)
        self._lock = RLock()

    def append(self, message: ConversationMessage) -> None:
        with self._lock:
            key = (message.tenant_id, message.conversation_id)
            rank = self._next[key]
            self._next[key] = rank + 1
            self._items.append(message.model_copy(update={"sequence": rank}))

    def list_for_conversation(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        limit: int,
    ) -> tuple[ConversationMessage, ...]:
        with self._lock:
            matching = [
                message
                for message in self._items
                if message.tenant_id == tenant_id
                and message.conversation_id == conversation_id
            ]
        # Oldest first, and the cap keeps the newest turns when a thread outgrows it:
        # truncating the end would hide the part of the exchange a reader wants.
        matching.sort(key=lambda message: message.sequence)
        return tuple(matching[-limit:])
