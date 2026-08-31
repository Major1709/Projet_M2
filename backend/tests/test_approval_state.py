from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

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
from app.approvals.adapters.memory import InMemoryApprovalUnitOfWork
from app.approvals.errors import (
    ProposalConversationNotFound,
    ProposalExpired,
    SessionRequired,
)
from app.audit.adapters.memory import InMemoryAuditSink
from app.audit.domain import AuditEventType
from app.conversations.adapters.memory import InMemoryConversationRepository
from app.conversations.domain import Conversation
from app.core.identity import (
    DEV_HEADERS_MODE,
    SESSION_MODE,
    SecurityContext,
    security_context_fingerprint,
)
from app.mcp import (
    MCPExecutionResult,
    PermissionDecision,
    SourceSystem,
    ToolActionClass,
)
from app.mcp.adapters.idempotency import InMemoryMutationIdempotencyStore

CONVERSATION_ID = uuid4()
SESSION_ID = uuid4()
PINNED_SCHEMA = "a" * 64
APPROVAL_TTL_SECONDS = 900


class StubToolPin:
    """Stands in for the mutation registry, which does not exist yet.

    The production adapter denies every tool, so proposing anything through it is
    impossible by design; these tests exercise the approval machinery itself, not the
    registry. ``schema_sha256`` is mutable so a test can simulate a provider changing
    its schema between approval and execution.
    """

    def __init__(self, digest: str = PINNED_SCHEMA) -> None:
        self.digest = digest

    def schema_sha256(self, *, source_system: SourceSystem, tool_name: str) -> str:
        del source_system, tool_name
        return self.digest


def workflow_for(
    unit_of_work,
    conversations,
    *,
    tool_pin=None,
    ttl=APPROVAL_TTL_SECONDS,
    auth_mode=SESSION_MODE,
):
    # Session mode by default: these tests exercise the rules a real deployment runs
    # under, and dev_headers exempts itself from the session binding.
    return ApprovalWorkflow(
        unit_of_work,
        conversations,
        tool_pin or StubToolPin(),
        ttl,
        auth_mode,
    )


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
    InMemoryApprovalUnitOfWork,
    InMemoryAuditSink,
    SecurityContext,
]:
    unit_of_work = InMemoryApprovalUnitOfWork()
    audit = unit_of_work.audit
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a", session_id=SESSION_ID)
    conversations = InMemoryConversationRepository()
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    return workflow_for(unit_of_work, conversations), unit_of_work, audit, context


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
    service, unit_of_work, _, context = setup
    proposal = service.propose(make_command(), context).proposal
    changed = proposal.model_copy(
        update={"state": ActionProposalState.REJECTED, "version": 2}
    )
    unit_of_work.proposals.replace(proposal=changed, expected_version=1)

    stale = proposal.model_copy(
        update={"state": ActionProposalState.APPROVED, "version": 2}
    )
    with pytest.raises(VersionConflict):
        unit_of_work.proposals.replace(proposal=stale, expected_version=1)


def test_proposal_and_audit_roll_back_together(monkeypatch: pytest.MonkeyPatch) -> None:
    unit_of_work = InMemoryApprovalUnitOfWork()
    conversations = InMemoryConversationRepository()
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a", session_id=SESSION_ID)
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    service = workflow_for(unit_of_work, conversations)
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
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a", session_id=SESSION_ID)
    service = workflow_for(unit_of_work, InMemoryConversationRepository())

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
        self.idempotency_keys: list[str] = []

    def execute_read(self, **_: Any) -> MCPExecutionResult:
        return MCPExecutionResult(succeeded=True)

    def execute_mutation(self, **kwargs: Any) -> MCPExecutionResult:
        self.mutation_calls += 1
        self.idempotency_keys.append(kwargs["idempotency_key"])
        return MCPExecutionResult(succeeded=True, external_ids=("CONF-42",))


class RaisingGateway(RecordingGateway):
    def execute_mutation(self, **kwargs: Any) -> MCPExecutionResult:
        self.mutation_calls += 1
        self.idempotency_keys.append(kwargs["idempotency_key"])
        raise RuntimeError("the provider connection dropped mid-write")


class AllowPermissionVerifier:
    def check(self, _: Any) -> PermissionDecision:
        return PermissionDecision(allowed=True, decision_id="permission-1")


def test_mcp_mutation_cannot_run_before_approval(setup: tuple) -> None:
    service, unit_of_work, audit, context = setup
    proposal = service.propose(make_command(), context).proposal
    gateway = RecordingGateway()
    executor = ApprovedMutationRunner(
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=AllowPermissionVerifier(),
        tool_pin=StubToolPin(),
        idempotency=InMemoryMutationIdempotencyStore(),
    )

    with pytest.raises(InvalidTransition, match="APPROVED"):
        executor.execute(
            proposal_id=proposal.id,
            expected_version=proposal.version,
            context=context,
        )

    assert gateway.mutation_calls == 0


def test_approved_mutation_is_reauthorized_then_executed(setup: tuple) -> None:
    service, unit_of_work, audit, context = setup
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
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=AllowPermissionVerifier(),
        tool_pin=StubToolPin(),
        idempotency=InMemoryMutationIdempotencyStore(),
    )

    result = executor.execute(
        proposal_id=approved.id,
        expected_version=approved.version,
        context=context,
    )

    assert result.succeeded is True
    assert gateway.mutation_calls == 1
    stored = unit_of_work.proposals.get(tenant_id=context.tenant_id, proposal_id=approved.id)
    assert stored is not None
    assert stored.state == ActionProposalState.COMPLETED


def test_a_decision_arriving_after_the_window_is_refused(setup: tuple) -> None:
    """Consent is spent by time, not only by use."""

    _, _, _, context = setup
    unit_of_work = InMemoryApprovalUnitOfWork()
    conversations = InMemoryConversationRepository()
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    # A window already closed by the time propose() returns, which is the only way to
    # observe the deadline without making the test wait on a clock.
    service = workflow_for(unit_of_work, conversations, ttl=0)
    issued = service.propose(make_command(), context)

    with pytest.raises(ProposalExpired):
        service.approve(
            issued.proposal.id,
            ActionDecision(
                expected_version=issued.proposal.version,
                decision_token=issued.decision_token,
            ),
            context,
        )


def test_expiry_answers_before_the_token_is_examined(setup: tuple) -> None:
    """An expired proposal must not tell a caller whether their token was right."""

    _, _, _, context = setup
    unit_of_work = InMemoryApprovalUnitOfWork()
    conversations = InMemoryConversationRepository()
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    service = workflow_for(unit_of_work, conversations, ttl=0)
    issued = service.propose(make_command(), context)

    with pytest.raises(ProposalExpired):
        service.approve(
            issued.proposal.id,
            ActionDecision(
                expected_version=issued.proposal.version,
                decision_token="x" * 40,
            ),
            context,
        )


def test_an_approved_mutation_expiring_before_execution_never_reaches_the_gateway(
    setup: tuple,
) -> None:
    service, unit_of_work, audit, context = setup
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
    # The approval was valid when granted; the delay is what withdraws it.
    expired = approved.model_copy(
        update={"expires_at": approved.created_at, "version": approved.version + 1}
    )
    unit_of_work.proposals.replace(proposal=expired, expected_version=approved.version)
    gateway = RecordingGateway()
    executor = ApprovedMutationRunner(
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=AllowPermissionVerifier(),
        tool_pin=StubToolPin(),
        idempotency=InMemoryMutationIdempotencyStore(),
    )

    with pytest.raises(ProposalExpired):
        executor.execute(
            proposal_id=expired.id,
            expected_version=expired.version,
            context=context,
        )

    assert gateway.mutation_calls == 0


def test_a_tool_schema_changing_after_approval_withdraws_it(setup: tuple) -> None:
    """The human approved one shape of call; a redefined tool is a different one."""

    service, unit_of_work, audit, context = setup
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
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=AllowPermissionVerifier(),
        tool_pin=StubToolPin("b" * 64),
        idempotency=InMemoryMutationIdempotencyStore(),
    )

    with pytest.raises(InvalidTransition, match="schema changed"):
        executor.execute(
            proposal_id=approved.id,
            expected_version=approved.version,
            context=context,
        )

    assert gateway.mutation_calls == 0


def test_a_revision_is_repinned_and_redated_rather_than_inheriting(setup: tuple) -> None:
    service, _, _, context = setup
    issued = service.propose(make_command(), context)
    proposal = issued.proposal

    revised = service.revise(
        proposal.id,
        ActionRevision(
            expected_version=proposal.version,
            decision_token=issued.decision_token,
            target=proposal.target,
            payload={"title": "Epic paiement", "body": "Version corrigee"},
            reason="Correction du corps",
        ),
        context,
    )

    # A full window, measured from the revision itself rather than inherited: a
    # revision granted near the original deadline must not hand back a window that is
    # nearly spent.
    #
    # Asserted as an approximate duration, and both halves of that matter. Not
    # "strictly later", because two proposals can be minted inside one tick of a
    # coarse system clock. Not an exact equality either: expires_at and created_at
    # come from two separate clock reads, so the difference is the window plus
    # however long the call took.
    window = revised.replacement.expires_at - revised.replacement.created_at
    assert abs(window - timedelta(seconds=APPROVAL_TTL_SECONDS)) < timedelta(seconds=1)
    assert revised.replacement.expires_at >= proposal.expires_at
    assert revised.replacement.tool_schema_sha256 == PINNED_SCHEMA


def approved_proposal(service, context):
    issued = service.propose(make_command(), context)
    proposal = issued.proposal
    return service.approve(
        proposal.id,
        ActionDecision(
            expected_version=proposal.version,
            decision_token=issued.decision_token,
        ),
        context,
    )


def runner_for(unit_of_work, gateway, store):
    return ApprovedMutationRunner(
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=AllowPermissionVerifier(),
        tool_pin=StubToolPin(),
        idempotency=store,
    )


def test_the_idempotency_key_is_minted_by_the_server_not_the_caller(setup: tuple) -> None:
    """execute() takes no key: a caller-chosen one could collide with another action."""

    import inspect

    service, unit_of_work, audit, context = setup
    approved = approved_proposal(service, context)
    gateway = RecordingGateway()
    runner_for(unit_of_work, gateway, InMemoryMutationIdempotencyStore()).execute(
        proposal_id=approved.id,
        expected_version=approved.version,
        context=context,
    )

    assert "idempotency_key" not in inspect.signature(ApprovedMutationRunner.execute).parameters
    assert len(gateway.idempotency_keys) == 1
    assert len(gateway.idempotency_keys[0]) >= 32


def test_a_completed_mutation_replays_its_outcome_instead_of_writing_twice(
    setup: tuple,
) -> None:
    service, unit_of_work, audit, context = setup
    approved = approved_proposal(service, context)
    gateway = RecordingGateway()
    store = InMemoryMutationIdempotencyStore()
    runner = runner_for(unit_of_work, gateway, store)

    first = runner.execute(
        proposal_id=approved.id,
        expected_version=approved.version,
        context=context,
    )
    stored = unit_of_work.proposals.get(tenant_id=context.tenant_id, proposal_id=approved.id)
    assert stored is not None
    second = runner.execute(
        proposal_id=approved.id,
        expected_version=stored.version,
        context=context,
    )

    # One approval, one write. The second call returns the record, not a new result.
    assert gateway.mutation_calls == 1
    assert second == first
    assert second.external_ids == ("CONF-42",)


def test_a_failed_call_keeps_the_same_key_for_the_retry(setup: tuple) -> None:
    """A raised call leaves the write in an unknown state, so the provider must be
    the one to decide whether it already applied it -- which needs the same key."""

    service, unit_of_work, audit, context = setup
    approved = approved_proposal(service, context)
    store = InMemoryMutationIdempotencyStore()
    failing = RaisingGateway()

    with pytest.raises(RuntimeError):
        runner_for(unit_of_work, failing, store).execute(
            proposal_id=approved.id,
            expected_version=approved.version,
            context=context,
        )

    stored = unit_of_work.proposals.get(tenant_id=context.tenant_id, proposal_id=approved.id)
    assert stored is not None
    assert stored.state == ActionProposalState.FAILED
    reservation = store.reserve(tenant_id=context.tenant_id, proposal_id=approved.id)
    assert reservation.completed is False
    assert reservation.idempotency_key == failing.idempotency_keys[0]


def test_a_source_denial_is_recorded_so_it_cannot_be_retried_until_it_passes(
    setup: tuple,
) -> None:
    service, unit_of_work, audit, context = setup
    approved = approved_proposal(service, context)
    gateway = RecordingGateway()
    store = InMemoryMutationIdempotencyStore()

    class DenyPermissionVerifier:
        def check(self, _: Any) -> PermissionDecision:
            return PermissionDecision(
                allowed=False,
                decision_id="permission-2",
                reason_code="FORBIDDEN",
            )

    runner = ApprovedMutationRunner(
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=DenyPermissionVerifier(),
        tool_pin=StubToolPin(),
        idempotency=store,
    )
    denied = runner.execute(
        proposal_id=approved.id,
        expected_version=approved.version,
        context=context,
    )

    assert denied.succeeded is False
    assert gateway.mutation_calls == 0
    reservation = store.reserve(tenant_id=context.tenant_id, proposal_id=approved.id)
    assert reservation.completed is True
    assert reservation.result == denied


def update_command(resource_version: str | None) -> ActionProposalCreate:
    return ActionProposalCreate(
        conversation_id=CONVERSATION_ID,
        source_system=SourceSystem.CONFLUENCE,
        tool_name="confluence.update_page",
        action_class=ToolActionClass.UPDATE,
        target=ActionTarget(
            source_system=SourceSystem.CONFLUENCE,
            resource_type="page",
            resource_id="98483",
            title="Modele de decision",
            resource_version=resource_version,
        ),
        payload={"title": "Modele de decision", "body": "Corps revu"},
        diff={"body": {"before": "Corps", "after": "Corps revu"}},
        correlation_id="corr-2",
    )


def test_touching_an_existing_resource_without_its_version_is_not_proposable() -> None:
    """An approval that cannot be revalidated could be spent on a changed target."""

    with pytest.raises(ValidationError, match="requires its version"):
        update_command(None)


def test_a_creation_needs_no_version_because_it_has_no_target_yet() -> None:
    assert make_command().target.resource_version is None


def test_the_verifier_is_told_which_version_the_human_was_shown(setup: tuple) -> None:
    service, unit_of_work, audit, context = setup
    issued = service.propose(update_command("7"), context)
    proposal = issued.proposal
    approved = service.approve(
        proposal.id,
        ActionDecision(
            expected_version=proposal.version,
            decision_token=issued.decision_token,
        ),
        context,
    )

    class CapturingVerifier:
        def __init__(self) -> None:
            self.seen: Any = None

        def check(self, request: Any) -> PermissionDecision:
            self.seen = request
            return PermissionDecision(allowed=True, decision_id="permission-1")

    verifier = CapturingVerifier()
    gateway = RecordingGateway()
    ApprovedMutationRunner(
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=verifier,
        tool_pin=StubToolPin(),
        idempotency=InMemoryMutationIdempotencyStore(),
    ).execute(
        proposal_id=approved.id,
        expected_version=approved.version,
        context=context,
    )

    assert verifier.seen.resource_id == "98483"
    assert verifier.seen.expected_resource_version == "7"
    assert verifier.seen.resource_type == "page"


def test_a_resource_changed_since_the_approval_is_never_written(setup: tuple) -> None:
    service, unit_of_work, audit, context = setup
    issued = service.propose(update_command("7"), context)
    proposal = issued.proposal
    approved = service.approve(
        proposal.id,
        ActionDecision(
            expected_version=proposal.version,
            decision_token=issued.decision_token,
        ),
        context,
    )

    class DriftDetectingVerifier:
        """Stands for a source read finding a version other than the approved one."""

        def check(self, request: Any) -> PermissionDecision:
            if request.expected_resource_version != "9":
                return PermissionDecision(
                    allowed=False,
                    decision_id="permission-3",
                    reason_code="RESOURCE_CHANGED",
                )
            return PermissionDecision(allowed=True, decision_id="permission-3")

    gateway = RecordingGateway()
    result = ApprovedMutationRunner(
        unit_of_work=unit_of_work,
        gateway=gateway,
        permission_verifier=DriftDetectingVerifier(),
        tool_pin=StubToolPin(),
        idempotency=InMemoryMutationIdempotencyStore(),
    ).execute(
        proposal_id=approved.id,
        expected_version=approved.version,
        context=context,
    )

    assert result.succeeded is False
    assert result.error_code == "RESOURCE_CHANGED"
    assert gateway.mutation_calls == 0
    stored = unit_of_work.proposals.get(tenant_id=context.tenant_id, proposal_id=approved.id)
    assert stored is not None
    assert stored.state == ActionProposalState.DENIED


def test_a_state_change_and_its_trail_commit_together(setup: tuple) -> None:
    """A state that advanced on a trail nobody could write is the one thing an audit
    exists to rule out, so the two share a transaction and fall together."""

    service, unit_of_work, audit, context = setup
    approved = approved_proposal(service, context)
    before = len(audit.snapshot())

    def refuse(event: Any) -> None:
        raise RuntimeError("the audit storage is unavailable")

    unit_of_work.audit.append = refuse  # type: ignore[method-assign]
    gateway = RecordingGateway()

    with pytest.raises(RuntimeError, match="audit storage"):
        runner_for(unit_of_work, gateway, InMemoryMutationIdempotencyStore()).execute(
            proposal_id=approved.id,
            expected_version=approved.version,
            context=context,
        )

    stored = unit_of_work.proposals.get(
        tenant_id=context.tenant_id, proposal_id=approved.id
    )
    assert stored is not None
    # Rolled back to the state the last committed transaction left, never to EXECUTING.
    assert stored.state == ActionProposalState.PERMISSION_CHECK
    assert len(audit.snapshot()) == before
    # And the provider was never contacted: the trail comes first or not at all.
    assert gateway.mutation_calls == 0


def test_a_dispatch_is_recorded_before_the_provider_is_contacted(setup: tuple) -> None:
    """The outbox record. An external write cannot join our transaction, so what is
    committed beforehand is the intent -- naming the key the call goes out under, so a
    write interrupted mid-flight can still be reconciled with the provider."""

    service, unit_of_work, audit, context = setup
    approved = approved_proposal(service, context)
    failing = RaisingGateway()

    with pytest.raises(RuntimeError):
        runner_for(unit_of_work, failing, InMemoryMutationIdempotencyStore()).execute(
            proposal_id=approved.id,
            expected_version=approved.version,
            context=context,
        )

    dispatched = [
        event
        for event in audit.snapshot()
        if event.event_type == AuditEventType.MUTATION_DISPATCHED
    ]
    assert len(dispatched) == 1
    assert dispatched[0].details["idempotency_key"] == failing.idempotency_keys[0]
    assert dispatched[0].details["state"] == ActionProposalState.EXECUTING


def test_two_sessions_of_one_user_do_not_share_a_fingerprint() -> None:
    """The session is part of the identity, so it must change the binding."""

    signed_in = SecurityContext(
        tenant_id="tenant-a", user_id="user-a", session_id=SESSION_ID
    )
    signed_in_again = signed_in.model_copy(update={"session_id": uuid4()})

    assert security_context_fingerprint(signed_in) != security_context_fingerprint(
        signed_in_again
    )


def test_a_mutation_cannot_be_proposed_without_a_sign_in() -> None:
    """Consent nothing can be held to is not consent, so it is never minted."""

    unit_of_work = InMemoryApprovalUnitOfWork()
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")
    conversations = InMemoryConversationRepository()
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    service = workflow_for(unit_of_work, conversations)

    with pytest.raises(SessionRequired, match="authenticated session"):
        service.propose(make_command(), context)

    assert unit_of_work.proposals.snapshot() == ()


def test_dev_headers_is_exempt_because_it_has_no_sign_in_to_bind() -> None:
    """The caller already names their own tenant in a header there; demanding a
    session would remove the approval path from local development and guarantee
    nothing in exchange."""

    unit_of_work = InMemoryApprovalUnitOfWork()
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")
    conversations = InMemoryConversationRepository()
    conversations.add(
        Conversation(
            id=CONVERSATION_ID,
            tenant_id=context.tenant_id,
            owner_user_id=context.user_id,
        )
    )
    service = workflow_for(unit_of_work, conversations, auth_mode=DEV_HEADERS_MODE)

    assert service.propose(make_command(), context).proposal is not None


def test_an_approval_cannot_be_spent_from_a_different_session(setup: tuple) -> None:
    """Signing out and back in ends the consent given in the session before it, and a
    stolen cookie stops being enough once the user has a new session."""

    service, unit_of_work, _, context = setup
    approved = approved_proposal(service, context)
    elsewhere = context.model_copy(update={"session_id": uuid4()})
    gateway = RecordingGateway()

    with pytest.raises(InvalidTransition, match="execution context"):
        runner_for(unit_of_work, gateway, InMemoryMutationIdempotencyStore()).execute(
            proposal_id=approved.id,
            expected_version=approved.version,
            context=elsewhere,
        )

    assert gateway.mutation_calls == 0


def confluence_update(
    *,
    resource_id: str = "98483",
    payload: dict[str, Any] | None = None,
    container_id: str | None = None,
) -> ActionProposalCreate:
    return ActionProposalCreate(
        conversation_id=CONVERSATION_ID,
        source_system=SourceSystem.CONFLUENCE,
        tool_name="confluence.update_page",
        action_class=ToolActionClass.UPDATE,
        target=ActionTarget(
            source_system=SourceSystem.CONFLUENCE,
            resource_type="page",
            resource_id=resource_id,
            title="Modele de decision",
            resource_version="7",
            container_id=container_id,
        ),
        payload=payload if payload is not None else {"body": "Corps revu"},
        diff={"body": {"before": "Corps", "after": "Corps revu"}},
        correlation_id="corr-b01",
    )


def test_a_payload_naming_a_different_resource_than_the_target_is_refused() -> None:
    """The finding B-01 in one line: the preview shows page A, the call writes page B.

    For a DELETE the shown title can be perfectly valid while the id underneath is
    another page entirely, so the approver sees a resource they recognise and
    consents to the destruction of one they never saw.
    """

    with pytest.raises(ValidationError, match="not the approved target"):
        confluence_update(payload={"pageId": "12345", "body": "Corps revu"})


def test_a_payload_naming_the_same_resource_is_accepted() -> None:
    """The rule refuses contradiction, not repetition."""

    assert confluence_update(payload={"pageId": "98483", "body": "Corps revu"})


def test_a_creation_cannot_name_an_existing_resource_in_its_payload() -> None:
    """There is no target to compare against, so any named resource is a smuggled one."""

    with pytest.raises(ValidationError, match="cannot name an existing resource"):
        ActionProposalCreate(
            conversation_id=CONVERSATION_ID,
            source_system=SourceSystem.CONFLUENCE,
            tool_name="confluence.create_page",
            action_class=ToolActionClass.CREATE,
            target=ActionTarget(
                source_system=SourceSystem.CONFLUENCE,
                resource_type="page",
                title="Nouvelle page",
            ),
            payload={"pageId": "98483", "title": "Nouvelle page"},
            correlation_id="corr-b01",
        )


def test_a_payload_container_that_contradicts_the_target_is_refused() -> None:
    """Writing into another space is the same defect one level up."""

    with pytest.raises(ValidationError, match="not the approved container"):
        confluence_update(
            container_id="SPACE-1",
            payload={"spaceId": "SPACE-9", "body": "Corps revu"},
        )


def test_an_identifier_nested_in_the_body_is_content_not_a_target() -> None:
    """A page id inside a body is something someone wrote about a page. Refusing it
    would reject legitimate proposals, and the arguments a tool acts on are the
    top-level ones."""

    assert confluence_update(payload={"body": {"pageId": "12345", "text": "cf. 12345"}})


def test_a_record_that_no_longer_matches_its_hash_is_never_executed(
    setup: tuple,
) -> None:
    """Recomputed from the record's own fields immediately before the write, so a
    row changed since the approval -- a partial write, a mapping defect -- stops the
    mutation instead of being sent to the provider."""

    service, unit_of_work, _, context = setup
    approved = approved_proposal(service, context)
    tampered = approved.model_copy(
        update={
            "payload_json": '{"title": "Epic paiement", "body": "Corps substitue"}',
            "version": approved.version + 1,
        }
    )
    unit_of_work.proposals.replace(proposal=tampered, expected_version=approved.version)
    gateway = RecordingGateway()

    with pytest.raises(InvalidTransition, match="no longer matches its hash"):
        runner_for(unit_of_work, gateway, InMemoryMutationIdempotencyStore()).execute(
            proposal_id=tampered.id,
            expected_version=tampered.version,
            context=context,
        )

    assert gateway.mutation_calls == 0
