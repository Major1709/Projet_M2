from datetime import UTC, datetime
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

