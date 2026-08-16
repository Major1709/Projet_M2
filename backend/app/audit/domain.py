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
    MCP_READ_AUTHORIZED = "MCP_READ_AUTHORIZED"
    MCP_READ_COMPLETED = "MCP_READ_COMPLETED"
    MCP_READ_FAILED = "MCP_READ_FAILED"
    # Four types rather than one with a verdict field, to match the MCP reads: an
    # authorization written before the call is what makes an unrecorded call
    # impossible, and a verdict field on a single event cannot express that.
    LLM_INVOCATION_AUTHORIZED = "LLM_INVOCATION_AUTHORIZED"
    LLM_INVOCATION_COMPLETED = "LLM_INVOCATION_COMPLETED"
    LLM_INVOCATION_REFUSED = "LLM_INVOCATION_REFUSED"
    # Separate from REFUSED because a bounded call may have produced a partial
    # answer that our own ceiling cut short. That is a fact about the content, not
    # about the provider, and collapsing it into a refusal would hide truncation.
    LLM_INVOCATION_BOUNDED = "LLM_INVOCATION_BOUNDED"


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

