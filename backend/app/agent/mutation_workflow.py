import hmac
from datetime import UTC, datetime
from uuid import UUID

from app.approvals.domain import ActionProposal, ActionProposalState
from app.approvals.errors import InvalidTransition, ProposalExpired
from app.approvals.ports import ApprovalRepository, MutationToolPin
from app.audit.domain import AuditEvent, AuditEventType
from app.audit.ports import AuditSink
from app.core.identity import SecurityContext, security_context_fingerprint
from app.mcp.domain import MCPExecutionResult, MCPToolCall, PermissionCheck
from app.mcp.ports import (
    MCPToolGateway,
    MutationIdempotencyStore,
    SourcePermissionVerifier,
)


class ApprovedMutationRunner:
    """Fail-closed mutation façade enforcing approval and source reauthorization."""

    def __init__(
        self,
        *,
        repository: ApprovalRepository,
        gateway: MCPToolGateway,
        permission_verifier: SourcePermissionVerifier,
        tool_pin: MutationToolPin,
        idempotency: MutationIdempotencyStore,
        audit_sink: AuditSink,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._permission_verifier = permission_verifier
        self._tool_pin = tool_pin
        self._idempotency = idempotency
        self._audit_sink = audit_sink

    def execute(
        self,
        *,
        proposal_id: UUID,
        expected_version: int,
        context: SecurityContext,
    ) -> MCPExecutionResult:
        proposal = self._repository.get(
            tenant_id=context.tenant_id,
            proposal_id=proposal_id,
        )
        if proposal is None:
            from app.approvals.errors import ProposalNotFound

            raise ProposalNotFound(proposal_id)
        if proposal.version != expected_version:
            from app.approvals.errors import VersionConflict

            raise VersionConflict(expected=expected_version, actual=proposal.version)
        # Answered before every state check, because a mutation that already ran left
        # the proposal COMPLETED rather than APPROVED. This is a lookup, not a
        # reservation: nothing is minted for a proposal that never reached execution.
        finished = self._idempotency.find(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.id,
        )
        if finished is not None and finished.completed:
            if finished.result is None:
                raise InvalidTransition("A completed mutation has no recorded outcome")
            return finished.result

        # An approval that outlived its window is spent, and saying so first keeps a
        # stale proposal from reporting an identity or context mismatch that is merely
        # a consequence of the delay.
        if proposal.has_expired():
            raise ProposalExpired(
                "The approval expired before execution; propose the action again"
            )
        if proposal.state != ActionProposalState.APPROVED:
            raise InvalidTransition(
                "MCP mutation execution requires an APPROVED action proposal"
            )
        if proposal.approved_by_user_id != context.user_id:
            raise InvalidTransition("The mutation identity must be the recorded approver")
        if proposal.execution_context_hash != security_context_fingerprint(context):
            raise InvalidTransition("The approved execution context has changed")
        if not proposal.action_class.is_external_mutation:
            raise InvalidTransition("The approved action is not an external mutation")
        # The human consented to one shape of call. A provider that changed its schema
        # since then has changed what that consent covers, so it is withdrawn.
        current_schema = self._tool_pin.schema_sha256(
            source_system=proposal.source_system,
            tool_name=proposal.tool_name,
        )
        if not hmac.compare_digest(current_schema, proposal.tool_schema_sha256):
            raise InvalidTransition("The tool schema changed after the approval")

        call = MCPToolCall(
            source_system=proposal.source_system,
            tool_name=proposal.tool_name,
            action_class=proposal.action_class,
            arguments=proposal.payload,
            correlation_id=proposal.correlation_id,
        )
        # Reserved before anything is attempted, and durable at that point: the key
        # must survive a crash, or a retry would mint a second one and the provider
        # would treat one approved action as two requests.
        reservation = self._idempotency.reserve(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.id,
        )
        checking = self._transition(proposal, ActionProposalState.PERMISSION_CHECK)
        decision = self._permission_verifier.check(
            PermissionCheck(
                context=context,
                call=call,
                resource_type=proposal.target.resource_type,
                resource_id=proposal.target.resource_id,
                # The version the human was shown. The verifier compares it against
                # what the source holds now, so a resource edited between approval and
                # execution is refused rather than overwritten.
                expected_resource_version=proposal.target.resource_version,
                container_id=proposal.target.container_id,
            )
        )
        self._audit(
            checking,
            context,
            AuditEventType.MUTATION_PERMISSION_CHECKED,
            {"allowed": decision.allowed, "decision_id": decision.decision_id},
        )
        if not decision.allowed:
            self._transition(checking, ActionProposalState.DENIED)
            denial = MCPExecutionResult(
                succeeded=False,
                error_code=decision.reason_code or "SOURCE_PERMISSION_DENIED",
                safe_message="The source system denied this action",
            )
            # Recorded like any terminal outcome. A refusal that left the reservation
            # open would let the same approval be retried until the source happened to
            # allow it.
            self._idempotency.record_outcome(
                tenant_id=proposal.tenant_id,
                proposal_id=proposal.id,
                result=denial,
            )
            return denial

        executing = self._transition(checking, ActionProposalState.EXECUTING)
        try:
            result = self._gateway.execute_mutation(
                call=call,
                context=context,
                idempotency_key=reservation.idempotency_key,
            )
        except Exception:
            # The reservation stays open, deliberately. A raised call leaves the write
            # in an unknown state, so the honest retry re-presents the SAME key and
            # lets the provider decide whether it already applied it. Recording an
            # outcome here would claim knowledge we do not have.
            failed = self._transition(executing, ActionProposalState.FAILED)
            self._audit(failed, context, AuditEventType.MUTATION_FAILED, {})
            raise

        terminal_state = (
            ActionProposalState.PARTIAL
            if result.partial
            else ActionProposalState.COMPLETED
            if result.succeeded
            else ActionProposalState.FAILED
        )
        terminal = self._transition(executing, terminal_state)
        self._idempotency.record_outcome(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.id,
            result=result,
        )
        self._audit(
            terminal,
            context,
            AuditEventType.MUTATION_EXECUTED
            if result.succeeded
            else AuditEventType.MUTATION_FAILED,
            {
                "succeeded": result.succeeded,
                "partial": result.partial,
                "external_ids": result.external_ids,
                "error_code": result.error_code,
            },
        )
        return result

    def _transition(
        self,
        proposal: ActionProposal,
        state: ActionProposalState,
    ) -> ActionProposal:
        changed = proposal.model_copy(
            update={
                "state": state,
                "version": proposal.version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.replace(proposal=changed, expected_version=proposal.version)
        return changed

    def _audit(
        self,
        proposal: ActionProposal,
        context: SecurityContext,
        event_type: AuditEventType,
        details: dict[str, object],
    ) -> None:
        self._audit_sink.append(
            AuditEvent(
                event_type=event_type,
                tenant_id=proposal.tenant_id,
                actor_user_id=context.user_id,
                correlation_id=proposal.correlation_id,
                action_proposal_id=proposal.id,
                details={"state": proposal.state, "version": proposal.version, **details},
            )
        )
