from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AuditEventType(StrEnum):
    ACTION_PROPOSED = "ACTION_PROPOSED"
    ACTION_APPROVED = "ACTION_APPROVED"
    ACTION_REJECTED = "ACTION_REJECTED"
    ACTION_REVISED = "ACTION_REVISED"
    MUTATION_PERMISSION_CHECKED = "MUTATION_PERMISSION_CHECKED"
    MUTATION_EXECUTED = "MUTATION_EXECUTED"
    MUTATION_FAILED = "MUTATION_FAILED"


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    event_type: AuditEventType
    tenant_id: str
    actor_user_id: str
    correlation_id: str
    action_proposal_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

