import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.mcp.domain import MCPExecutionResult, SourceSystem, ToolActionClass


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
    # The version the human was shown, as the source states it -- a Confluence version
    # number, a Jira updated timestamp, an ETag. Opaque here on purpose: only the
    # source can say what its own version means, and comparing it just before writing
    # is what tells us the target has not moved since the approval.
    resource_version: str | None = Field(default=None, max_length=200)


# Payload keys that name the resource an action touches, and the container it sits
# in, per source system. Taken from the argument names the read registry already
# uses rather than invented, plus the obvious aliases a provider might accept.
#
# Deliberately generous: checking a key that never appears costs nothing, while a
# key that names a resource and goes unchecked is the whole defect this guards. The
# list is not derived from a mutation registry because none exists yet -- when one
# does, the canonical command should replace this map rather than extend it.
_RESOURCE_KEYS: dict[SourceSystem, tuple[str, ...]] = {
    SourceSystem.CONFLUENCE: ("pageId", "id"),
    SourceSystem.JIRA: ("issueIdOrKey", "issueId", "issueKey", "key"),
}
_CONTAINER_KEYS: dict[SourceSystem, tuple[str, ...]] = {
    SourceSystem.CONFLUENCE: ("spaceId", "spaceKey"),
    SourceSystem.JIRA: ("projectKey", "projectId"),
}


def _named_in(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    """Top-level payload entries that name a resource, as strings.

    Top level only, on purpose: that is where a tool's arguments live. A pageId
    nested inside a body is content someone wrote about a page, not the page this
    call acts on, and treating it as a target would refuse legitimate proposals.
    """

    return {
        key: str(payload[key])
        for key in keys
        if key in payload and payload[key] is not None
    }


def canonical_hash(
    *,
    source_system: SourceSystem,
    tool_name: str,
    action_class: ToolActionClass,
    target: "ActionTarget",
    payload: dict[str, Any],
    diff: dict[str, Any] | None,
    execution_context_hash: str,
    tool_schema_sha256: str,
) -> str:
    """One definition of what a proposal *is*, used to mint the hash and to recheck it.

    Written once rather than twice on purpose: two copies of a canonicalisation drift,
    and a recheck computed differently from the mint would either always pass or
    always fail, which are the two ways an integrity check becomes decoration.
    """

    return sha256_text(
        canonical_json(
            {
                "source_system": source_system,
                "tool_name": tool_name,
                "action_class": action_class,
                "target": target.model_dump(mode="json"),
                "payload": payload,
                "diff": diff,
                "execution_context_hash": execution_context_hash,
                "tool_schema_sha256": tool_schema_sha256,
            }
        )
    )


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
        # Without it the resource cannot be revalidated before the write, so the
        # approval could be spent on something that changed since it was shown. A
        # CREATE has no target yet, so it is exempt.
        if self.action_class != ToolActionClass.CREATE and not self.target.resource_version:
            raise ValueError(
                "A proposal touching an existing resource requires its version"
            )
        self._refuse_a_payload_that_contradicts_the_target()
        return self

    def _refuse_a_payload_that_contradicts_the_target(self) -> None:
        """The preview and the call must be about the same resource.

        The target is what a human is shown and decides on; the payload is what is
        actually sent. Nothing else ties them together, so a proposal could display a
        page the approver recognises while the arguments designate another -- for a
        DELETE, a valid-looking title over a different id. Refused at construction:
        an approval granted on that pair could never be honestly executed.
        """

        named = _named_in(self.payload, _RESOURCE_KEYS.get(self.source_system, ()))
        for key, value in named.items():
            if self.target.resource_id is None:
                raise ValueError(
                    f"A creation cannot name an existing resource in its payload ({key})"
                )
            if value != self.target.resource_id:
                raise ValueError(
                    f"The payload resource in {key} is not the approved target"
                )
        containers = _named_in(self.payload, _CONTAINER_KEYS.get(self.source_system, ()))
        for key, value in containers.items():
            if self.target.container_id is not None and value != self.target.container_id:
                raise ValueError(
                    f"The payload container in {key} is not the approved container"
                )


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
        return cls(
            tenant_id=tenant_id,
            conversation_id=command.conversation_id,
            proposed_by_user_id=proposed_by_user_id,
            source_system=command.source_system,
            tool_name=command.tool_name,
            action_class=command.action_class,
            target=command.target,
            payload_json=payload_json,
            payload_hash=canonical_hash(
                source_system=command.source_system,
                tool_name=command.tool_name,
                action_class=command.action_class,
                target=command.target,
                payload=command.payload,
                diff=command.diff,
                execution_context_hash=execution_context_hash,
                tool_schema_sha256=tool_schema_sha256,
            ),
            explanation=command.explanation,
            diff_json=diff_json,
            correlation_id=command.correlation_id,
            execution_context_hash=execution_context_hash,
            tool_schema_sha256=tool_schema_sha256,
            expires_at=expires_at,
            decision_token_hash=decision_token_hash,
            supersedes_id=supersedes_id,
        )

    def recomputed_hash(self) -> str:
        """The hash this record would have if it were minted from its own fields now.

        Compared against the stored ``payload_hash`` just before the write. It catches
        a record that changed between the approval and the execution: a partial write,
        a mapping defect, a migration that dropped a column.

        What it does NOT do is authenticate the record. Anyone able to rewrite the row
        can rewrite the hash beside it, so this is an integrity check and not a
        signature. Making it one means an HMAC under a server-held key, which is a
        worthwhile upgrade and a key-management decision, not a line of code.
        """

        return canonical_hash(
            source_system=self.source_system,
            tool_name=self.tool_name,
            action_class=self.action_class,
            target=self.target,
            payload=self.payload,
            diff=self.diff,
            execution_context_hash=self.execution_context_hash,
            tool_schema_sha256=self.tool_schema_sha256,
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


class MutationExecution(BaseModel):
    """Ce qu'un client envoie pour depenser une approbation.

    ``expected_version`` n'est pas une formalite. Entre le moment ou une interface
    affiche une proposition et celui ou quelqu'un clique, elle a pu etre revisee,
    rejetee ou deja executee. Sans cette version, le second clic depenserait une
    approbation qui n'est plus celle qui a ete montree -- et la version est le seul
    element que le client possede deja, donc l'exiger ne lui coute rien.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_version: int = Field(ge=0)


class MutationExecutionView(BaseModel):
    """L'issue d'une ecriture, telle qu'une interface peut l'afficher.

    Ne porte ni la reponse du fournisseur ni la cle d'idempotence. La premiere est du
    contenu de source, qui a sa place dans une lecture tracee et pas dans le retour
    d'une ecriture ; la seconde est un detail de reprise cote serveur, et un client
    qui la verrait finirait par la renvoyer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    succeeded: bool
    partial: bool
    # La cle du ticket cree, quand le fournisseur la nomme. Vide n'est pas un echec :
    # rien n'oblige un fournisseur a nommer ce qu'il vient de creer.
    external_ids: tuple[str, ...]
    error_code: str | None
    # Deja destinee a etre lue par un humain, et deja depourvue de detail interne :
    # elle vient de la passerelle, qui ne met jamais la reponse du fournisseur dedans.
    safe_message: str | None

    @classmethod
    def from_domain(cls, result: MCPExecutionResult) -> "MutationExecutionView":
        return cls(
            succeeded=result.succeeded,
            partial=result.partial,
            external_ids=result.external_ids,
            error_code=result.error_code,
            safe_message=result.safe_message,
        )
