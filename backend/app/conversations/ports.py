from typing import Protocol
from uuid import UUID

from app.conversations.domain import Conversation, ConversationMessage


class ConversationRepository(Protocol):
    def add(self, conversation: Conversation) -> None: ...

    def get(self, *, tenant_id: str, conversation_id: UUID) -> Conversation | None: ...


class ConversationMessageRepository(Protocol):
    """Durable conversation turns.

    Separate from ``ConversationRepository`` because the two have different failure
    policies: a thread that cannot be created fails the request, a turn that cannot
    be recorded does not discard an answer already paid for.
    """

    def append(self, message: ConversationMessage) -> None: ...

    def list_for_conversation(
        self,
        *,
        tenant_id: str,
        conversation_id: UUID,
        limit: int,
    ) -> tuple[ConversationMessage, ...]: ...
