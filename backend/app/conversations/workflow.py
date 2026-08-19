from uuid import UUID

from app.conversations.domain import (
    CitedSource,
    Conversation,
    ConversationCreate,
    ConversationMessage,
    MessageRole,
    MessageStatus,
)
from app.conversations.errors import ConversationNotFound
from app.conversations.ports import ConversationMessageRepository, ConversationRepository
from app.core.identity import SecurityContext

# A conversation is read whole, so the ceiling is what stops one long thread from
# becoming an unbounded response. Server-side and not negotiable by the caller,
# for the same reason the read ceiling is not.
MAX_MESSAGES_RETURNED = 200


class ConversationWorkflow:
    """Owns conversation creation, turn recording and tenant/owner visibility rules."""

    def __init__(
        self,
        repository: ConversationRepository,
        messages: ConversationMessageRepository,
    ) -> None:
        self._repository = repository
        self._messages = messages

    def create(
        self,
        command: ConversationCreate,
        context: SecurityContext,
    ) -> Conversation:
        conversation = Conversation(
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
            title=command.title,
        )
        self._repository.add(conversation)
        return conversation

    def get(self, conversation_id: UUID, context: SecurityContext) -> Conversation:
        conversation = self._repository.get(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
        )
        if conversation is None or conversation.owner_user_id != context.user_id:
            raise ConversationNotFound(conversation_id)
        return conversation

    def append_message(
        self,
        *,
        conversation_id: UUID,
        context: SecurityContext,
        role: MessageRole,
        content: str,
        correlation_id: str,
        status: MessageStatus = MessageStatus.COMPLETE,
        sources: tuple[CitedSource, ...] = (),
    ) -> ConversationMessage:
        """Record one turn, after proving the caller owns the thread.

        The ownership check runs here rather than being left to the foreign key: the
        database would reject the write, but only with a constraint violation, which
        tells a caller that the row is invalid instead of that the thread is not
        theirs.
        """

        self.get(conversation_id, context)
        message = ConversationMessage(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            author_user_id=context.user_id,
            role=role,
            content=content,
            correlation_id=correlation_id,
            status=status,
            sources=sources,
        )
        self._messages.append(message)
        return message

    def list_messages(
        self,
        conversation_id: UUID,
        context: SecurityContext,
        limit: int = MAX_MESSAGES_RETURNED,
    ) -> tuple[ConversationMessage, ...]:
        self.get(conversation_id, context)
        return self._messages.list_for_conversation(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            limit=min(max(limit, 1), MAX_MESSAGES_RETURNED),
        )
