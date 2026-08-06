from typing import Protocol
from uuid import UUID

from app.conversations.domain import Conversation


class ConversationRepository(Protocol):
    def add(self, conversation: Conversation) -> None: ...

    def get(self, *, tenant_id: str, conversation_id: UUID) -> Conversation | None: ...
