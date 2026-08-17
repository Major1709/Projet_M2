from typing import Any
from uuid import uuid4

import pytest

from app.agent import ApprovedMutationRunner
from app.approvals import (
    ActionDecision,
    ActionProposalCreate,
    ActionProposalState,
    ActionRevision,
    ActionTarget,
    ApprovalWorkflow,
    InvalidTransition,
    VersionConflict,
)
from app.approvals.adapters.memory import (
    InMemoryActionProposalRepository,
    InMemoryApprovalUnitOfWork,
)
from app.approvals.errors import ProposalConversationNotFound
from app.audit.adapters.memory import InMemoryAuditSink
from app.conversations.adapters.memory import InMemoryConversationRepository
from app.conversations.domain import Conversation
from app.core.identity import SecurityContext
from app.mcp import (
    MCPExecutionResult,
    PermissionDecision,
    SourceSystem,
    ToolActionClass,
)

CONVERSATION_ID = uuid4()


def make_command(payload: dict[str, Any] | None = None) -> ActionProposalCreate:
    return ActionProposalCreate(
        conversation_id=CONVERSATION_ID,
        source_system=SourceSystem.CONFLUENCE,
        tool_name="confluence.create_page",
        action_class=ToolActionClass.CREATE,
        target=ActionTarget(
            source_system=SourceSystem.CONFLUENCE,
            resource_type="page",
            container_id="SPACE-1",
            title="Epic paiement",
        ),
        payload=payload or {"title": "Epic paiement", "body": "Version exacte"},
        correlation_id="corr-1",
    )


@pytest.fixture
def setup() -> tuple[
    ApprovalWorkflow,
    InMemoryActionProposalRepository,
    InMemoryAuditSink,
    SecurityContext,
]:
    unit_of_work = InMemoryApprovalUnitOfWork()
    repository = unit_of_work.proposals
    audit = unit_of_work.audit
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")
    conversations = InMemoryConversationRepository()
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    return ApprovalWorkflow(unit_of_work, conversations), repository, audit, context


def test_approval_requires_expected_version_and_consumes_token(setup: tuple) -> None:
    service, _, _, context = setup
    issued = service.propose(make_command(), context)
    proposal = issued.proposal
    assert proposal.decision_token_hash is not None

    approved = service.approve(
        proposal.id,
        ActionDecision(
            expected_version=proposal.version,
            decision_token=issued.decision_token,
        ),
        context,
    )

    assert approved.state == ActionProposalState.APPROVED
    assert approved.version == 2
    assert approved.decision_token_hash is None

    with pytest.raises(InvalidTransition):
        service.approve(
            proposal.id,
            ActionDecision(
                expected_version=proposal.version,
                decision_token=issued.decision_token,
            ),
            context,
        )


def test_optimistic_conflict_does_not_overwrite_newer_state(setup: tuple) -> None:
    service, _, _, context = setup
    issued = service.propose(make_command(), context)
    proposal = issued.proposal

    service.reject(
        proposal.id,
        ActionDecision(
            expected_version=proposal.version,
            decision_token=issued.decision_token,
            reason="Not ready",
        ),
        context,
    )

    with pytest.raises(InvalidTransition):
        service.approve(
            proposal.id,
            ActionDecision(
                expected_version=proposal.version,
                decision_token=issued.decision_token,
            ),
            context,
        )


def test_repository_detects_a_stale_direct_replacement(setup: tuple) -> None:
    service, repository, _, context = setup
    proposal = service.propose(make_command(), context).proposal
    changed = proposal.model_copy(
        update={"state": ActionProposalState.REJECTED, "version": 2}
    )
    repository.replace(proposal=changed, expected_version=1)

    stale = proposal.model_copy(
        update={"state": ActionProposalState.APPROVED, "version": 2}
    )
    with pytest.raises(VersionConflict):
        repository.replace(proposal=stale, expected_version=1)


def test_proposal_and_audit_roll_back_together(monkeypatch: pytest.MonkeyPatch) -> None:
    unit_of_work = InMemoryApprovalUnitOfWork()
    conversations = InMemoryConversationRepository()
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    service = ApprovalWorkflow(unit_of_work, conversations)
    append = unit_of_work.audit.append

    def fail_after_append(event: Any) -> None:
        append(event)
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(unit_of_work.audit, "append", fail_after_append)

    with pytest.raises(RuntimeError, match="simulated audit failure"):
        service.propose(make_command(), context)

    assert unit_of_work.proposals.snapshot() == ()
    assert unit_of_work.audit.snapshot() == ()


def test_proposal_requires_an_owned_conversation() -> None:
    unit_of_work = InMemoryApprovalUnitOfWork()
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")
    service = ApprovalWorkflow(unit_of_work, InMemoryConversationRepository())

    with pytest.raises(ProposalConversationNotFound, match="Conversation not found"):
        service.propose(make_command(), context)

    assert unit_of_work.proposals.snapshot() == ()


def test_revision_supersedes_snapshot_and_requires_new_approval(setup: tuple) -> None:
    service, _, _, context = setup
    original_issue = service.propose(make_command(), context)
    original = original_issue.proposal

    revision_issue = service.revise(
        original.id,
        ActionRevision(
            expected_version=1,
            decision_token=original_issue.decision_token,
            target=original.target,
            payload={"title": "Epic paiement v2", "body": "Nouveau contenu"},
            reason="Clarify the story",
        ),
        context,
    )
    superseded = revision_issue.superseded
    replacement = revision_issue.replacement

    assert superseded.state == ActionProposalState.SUPERSEDED
    assert replacement.state == ActionProposalState.PENDING_APPROVAL
    assert replacement.supersedes_id == original.id
    assert replacement.payload_hash != original.payload_hash
    assert replacement.decision_token_hash is not None
    assert revision_issue.decision_token != original_issue.decision_token


class RecordingGateway:
    def __init__(self) -> None:
        self.mutation_calls = 0

    def execute_read(self, **_: Any) -> MCPExecutionResult:
        return MCPExecutionResult(succeeded=True)

    def execute_mutation(self, **_: Any) -> MCPExecutionResult:
        self.mutation_calls += 1
        return MCPExecutionResult(succeeded=True, external_ids=("CONF-42",))


class AllowPermissionVerifier:
    def check(self, _: Any) -> PermissionDecision:
        return PermissionDecision(allowed=True, decision_id="permission-1")


def test_mcp_mutation_cannot_run_before_approval(setup: tuple) -> None:
    service, repository, audit, context = setup
    proposal = service.propose(make_command(), context).proposal
    gateway = RecordingGateway()
    executor = ApprovedMutationRunner(
        repository=repository,
        gateway=gateway,
        permission_verifier=AllowPermissionVerifier(),
        audit_sink=audit,
    )

    with pytest.raises(InvalidTransition, match="APPROVED"):
        executor.execute(
            proposal_id=proposal.id,
            expected_version=proposal.version,
            context=context,
            idempotency_key="idempotency-1",
        )

    assert gateway.mutation_calls == 0


def test_approved_mutation_is_reauthorized_then_executed(setup: tuple) -> None:
    service, repository, audit, context = setup
    issued = service.propose(make_command(), context)
    proposal = issued.proposal
    approved = service.approve(
        proposal.id,
        ActionDecision(
            expected_version=proposal.version,
            decision_token=issued.decision_token,
        ),
        context,
    )
    gateway = RecordingGateway()
    executor = ApprovedMutationRunner(
        repository=repository,
        gateway=gateway,
        permission_verifier=AllowPermissionVerifier(),
        audit_sink=audit,
    )

    result = executor.execute(
        proposal_id=approved.id,
        expected_version=approved.version,
        context=context,
        idempotency_key="idempotency-1",
    )

    assert result.succeeded is True
    assert gateway.mutation_calls == 1
    stored = repository.get(tenant_id=context.tenant_id, proposal_id=approved.id)
    assert stored is not None
    assert stored.state == ActionProposalState.COMPLETED
