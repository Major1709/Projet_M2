from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=300)


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    owner_user_id: str
    title: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    COMPLETE = "complete"
    ERROR = "error"


class CitedSource(BaseModel):
    """One source an answer cited, as the read workflow observed it.

    A projection of the agent's ``AgentSource``, stored rather than recomputed so a
    reloaded answer shows the citations it was actually formed from. There is no
    confidence and no inferred flag: the backend derives citations from performed
    reads, so it has nothing truthful to put in either.
    """

    model_config = ConfigDict(frozen=True)

    source_system: str = Field(min_length=1, max_length=50)
    tool_name: str = Field(min_length=1, max_length=200)
    # ``None`` for a read that enumerates rather than designates.
    resource_reference: str | None = Field(default=None, max_length=2_000)
    retrieved_at: datetime
    truncated: bool = False


class ConversationMessage(BaseModel):
    """One turn of a conversation, owned by a tenant and by its author."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1, max_length=255)
    conversation_id: UUID
    author_user_id: str = Field(min_length=1, max_length=255)
    # Rank within the thread, assigned by the repository on append. Reading order
    # comes from this, never from the timestamp: one exchange writes both turns
    # inside a single clock tick.
    sequence: int = Field(default=0, ge=0)
    role: MessageRole
    content: str
    # Ties a displayed turn to the reads that produced it in the audit trail. Both
    # turns of one exchange carry the same value.
    correlation_id: str = Field(min_length=1, max_length=200)
    status: MessageStatus = MessageStatus.COMPLETE
    created_at: datetime = Field(default_factory=utc_now)
    sources: tuple[CitedSource, ...] = ()
