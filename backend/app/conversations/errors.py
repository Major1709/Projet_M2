from uuid import UUID


class ConversationNotFound(LookupError):
    def __init__(self, conversation_id: UUID) -> None:
        super().__init__(f"Conversation {conversation_id} was not found")
        self.conversation_id = conversation_id
