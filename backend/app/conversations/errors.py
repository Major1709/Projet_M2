from uuid import UUID


class ConversationNotFound(LookupError):
    # The same code a conversation owned by someone else returns, because the
    # route answers both alike -- a distinguishable code would turn the error
    # into a way of enumerating other people's threads.
    code = "CONVERSATION_NOT_FOUND"

    def __init__(self, conversation_id: UUID) -> None:
        super().__init__(f"Conversation {conversation_id} was not found")
        self.conversation_id = conversation_id
