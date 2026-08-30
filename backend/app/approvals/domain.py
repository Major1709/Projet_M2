import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.mcp.domain import SourceSystem, ToolActionClass


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActionProposalState(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    PERMISSION_CHECK = "PERMISSION_CHECK"
    DENIED = "DENIED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class ActionTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_system: SourceSystem
    resource_type: str = Field(min_length=1, max_length=100)
    resource_id: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=500)
    container_id: str | None = Field(default=None, max_length=500)


class ActionProposalCreate(BaseModel):
    conversation_id: UUID
    source_system: SourceSystem
    tool_name: str = Field(min_length=1, max_length=200)
    action_class: ToolActionClass
    target: ActionTarget
    payload: dict[str, Any]
    explanation: str | None = Field(default=None, max_length=2_000)
    diff: dict[str, Any] | None = None
    correlation_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_mutation_proposal(self) -> Self:
        if not self.action_class.is_external_mutation:
            raise ValueError("Only external mutations can become action proposals")
        if self.source_system == SourceSystem.KNOWLEDGE:
            raise ValueError("Knowledge index writes are internal, not MCP action proposals")
        if self.source_system != self.target.source_system:
            raise ValueError("The proposal and target source systems must match")
        if self.action_class == ToolActionClass.UPDATE and self.diff is None:
            raise ValueError("An UPDATE proposal requires an explicit diff")
        if self.action_class == ToolActionClass.DELETE and (
            not self.target.resource_id or not self.target.title
        ):
            raise ValueError("A DELETE proposal requires the target id and title")
        return self


class ActionRevision(BaseModel):
    expected_version: int = Field(ge=1)
    decision_token: str = Field(min_length=20, max_length=500)
    target: ActionTarget
    payload: dict[str, Any]
    explanation: str | None = Field(default=None, max_length=2_000)
    diff: dict[str, Any] | None = None
    reason: str = Field(min_length=1, max_length=2_000)


class ActionDecision(BaseModel):
    expected_version: int = Field(ge=1)
    decision_token: str = Field(min_length=20, max_length=500)
    reason: str | None = Field(default=None, max_length=2_000)


class ActionProposal(BaseModel):
    """Immutable proposal record. Transitions create a new version of this value."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    conversation_id: UUID
    proposed_by_user_id: str
    source_system: SourceSystem
    tool_name: str
    action_class: ToolActionClass
    target: ActionTarget
    payload_json: str
    payload_hash: str
    explanation: str | None = None
    diff_json: str | None = None
    correlation_id: str
    execution_context_hash: str
    # The tool schema the human was shown a payload for. Pinned at proposal time and
    # rechecked before execution: an approval is consent to one shape of call, and a
    # provider that changes its schema in between has changed what the approval means.
    tool_schema_sha256: str = Field(min_length=64, max_length=64)
    # An approval is a decision taken with what was on screen at that moment. Past this
    # instant the target may have moved, so consent is spent rather than merely stale.
    expires_at: datetime
    state: ActionProposalState = ActionProposalState.PENDING_APPROVAL
    version: int = 1
    decision_token_hash: str | None = Field(default=None, min_length=64, max_length=64)
    supersedes_id: UUID | None = None
    approved_by_user_id: str | None = None
    decision_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def from_command(
        cls,
        *,
        command: ActionProposalCreate,
        tenant_id: str,
        proposed_by_user_id: str,
        execution_context_hash: str,
        decision_token_hash: str,
        tool_schema_sha256: str,
        expires_at: datetime,
        supersedes_id: UUID | None = None,
    ) -> "ActionProposal":
        payload_json = canonical_json(command.payload)
        diff_json = canonical_json(command.diff) if command.diff is not None else None
        snapshot = {
            "source_system": command.source_system,
            "tool_name": command.tool_name,
            "action_class": command.action_class,
            "target": command.target.model_dump(mode="json"),
            "payload": command.payload,
            "diff": command.diff,
            "execution_context_hash": execution_context_hash,
            "tool_schema_sha256": tool_schema_sha256,
        }
        return cls(
            tenant_id=tenant_id,
            conversation_id=command.conversation_id,
            proposed_by_user_id=proposed_by_user_id,
            source_system=command.source_system,
            tool_name=command.tool_name,
            action_class=command.action_class,
            target=command.target,
            payload_json=payload_json,
            payload_hash=sha256_text(canonical_json(snapshot)),
            explanation=command.explanation,
            diff_json=diff_json,
            correlation_id=command.correlation_id,
            execution_context_hash=execution_context_hash,
            tool_schema_sha256=tool_schema_sha256,
            expires_at=expires_at,
            decision_token_hash=decision_token_hash,
            supersedes_id=supersedes_id,
        )

    def has_expired(self, *, now: datetime | None = None) -> bool:
        """True once consent is spent. Compared against a caller-supplied instant so
        the check is the same one in the workflow, the runner and the tests."""

        return (now or utc_now()) >= self.expires_at

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    @property
    def diff(self) -> dict[str, Any] | None:
        return json.loads(self.diff_json) if self.diff_json is not None else None


class ActionProposalView(BaseModel):
    id: UUID
    tenant_id: str
    conversation_id: UUID
    proposed_by_user_id: str
    source_system: SourceSystem
    tool_name: str
    action_class: ToolActionClass
    target: ActionTarget
    payload: dict[str, Any]
    payload_hash: str
    explanation: str | None
    diff: dict[str, Any] | None
    correlation_id: str
    execution_context_hash: str
    state: ActionProposalState
    version: int
    supersedes_id: UUID | None
    approved_by_user_id: str | None
    decision_reason: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, proposal: ActionProposal) -> "ActionProposalView":
        return cls(
            **proposal.model_dump(
                exclude={"payload_json", "diff_json", "decision_token_hash"}
            ),
            payload=proposal.payload,
            diff=proposal.diff,
        )


class ActionProposalCreatedView(ActionProposalView):
    decision_token: str


class ActionRevisionView(BaseModel):
    superseded: ActionProposalView
    replacement: ActionProposalView
    decision_token: str


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
