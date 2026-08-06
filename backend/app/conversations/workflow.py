from uuid import UUID

from app.conversations.domain import Conversation, ConversationCreate
from app.conversations.errors import ConversationNotFound
from app.conversations.ports import ConversationRepository
from app.core.identity import SecurityContext


class ConversationWorkflow:
    """Owns conversation creation and tenant/owner visibility rules."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

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
