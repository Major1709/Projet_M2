import hmac
from datetime import UTC, datetime
from uuid import UUID

from app.approvals.domain import ActionProposal, ActionProposalState
from app.approvals.errors import InvalidTransition, ProposalExpired
from app.approvals.ports import ApprovalUnitOfWorkFactory, MutationToolPin
from app.audit.domain import AuditEvent, AuditEventType
from app.core.identity import SecurityContext, security_context_fingerprint
from app.mcp.domain import MCPExecutionResult, MCPToolCall, PermissionCheck
from app.mcp.ports import (
    MCPToolGateway,
    MutationIdempotencyStore,
    SourcePermissionVerifier,
)


class ApprovedMutationRunner:
    """Fail-closed mutation façade enforcing approval and source reauthorization.

    Every state change is committed together with the audit event that explains it,
    through the approval unit of work. A trail written in its own transaction can be
    lost while the state advances, which produces the one thing an audit exists to
    rule out: a proposal that reached COMPLETED with nothing recording who spent it.
    """

    def __init__(
        self,
        *,
        unit_of_work: ApprovalUnitOfWorkFactory,
        gateway: MCPToolGateway,
        permission_verifier: SourcePermissionVerifier,
        tool_pin: MutationToolPin,
        idempotency: MutationIdempotencyStore,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._gateway = gateway
        self._permission_verifier = permission_verifier
        self._tool_pin = tool_pin
        self._idempotency = idempotency

    def execute(
        self,
        *,
        proposal_id: UUID,
        expected_version: int,
        context: SecurityContext,
    ) -> MCPExecutionResult:
        with self._unit_of_work() as unit:
            proposal = unit.proposals.get(
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
        # would treat one approved action as two requests. It deliberately stays out
        # of the transactions below -- a reservation rolled back alongside a failed
        # write would be reminted, the very outcome the key exists to prevent.
        reservation = self._idempotency.reserve(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.id,
        )
        # No event yet: the check has not run, so there is no verdict to record and
        # the state is the whole of what is known at this point.
        checking = self._advance(proposal, ActionProposalState.PERMISSION_CHECK, context)
        # Outside any transaction on purpose. The verifier reads the source over the
        # network, and a transaction held open across I/O keeps rows locked for as
        # long as the provider takes to answer.
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
        verdict: dict[str, object] = {
            "allowed": decision.allowed,
            "decision_id": decision.decision_id,
        }
        if not decision.allowed:
            self._advance(
                checking,
                ActionProposalState.DENIED,
                context,
                event_type=AuditEventType.MUTATION_PERMISSION_CHECKED,
                details=verdict,
            )
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

        # The outbox record. An external write cannot be enrolled in our transaction,
        # so what is made atomic instead is the statement of intent: the EXECUTING
        # state and the dispatch event commit together, before the provider is
        # contacted. A crash mid-call therefore always leaves a committed row naming
        # the call and the key it was sent under, which is exactly what is needed to
        # go and ask the provider whether the write landed. Recording afterwards
        # instead would allow a write that nothing accounts for.
        executing = self._advance(
            checking,
            ActionProposalState.EXECUTING,
            context,
            event_type=AuditEventType.MUTATION_DISPATCHED,
            details={**verdict, "idempotency_key": reservation.idempotency_key},
        )
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
            self._advance(
                executing,
                ActionProposalState.FAILED,
                context,
                event_type=AuditEventType.MUTATION_FAILED,
                details={"raised": True},
            )
            raise

        terminal_state = (
            ActionProposalState.PARTIAL
            if result.partial
            else ActionProposalState.COMPLETED
            if result.succeeded
            else ActionProposalState.FAILED
        )
        self._advance(
            executing,
            terminal_state,
            context,
            event_type=AuditEventType.MUTATION_EXECUTED
            if result.succeeded
            else AuditEventType.MUTATION_FAILED,
            details={
                "succeeded": result.succeeded,
                "partial": result.partial,
                "external_ids": result.external_ids,
                "error_code": result.error_code,
            },
        )
        self._idempotency.record_outcome(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal.id,
            result=result,
        )
        return result

    def _advance(
        self,
        proposal: ActionProposal,
        state: ActionProposalState,
        context: SecurityContext,
        *,
        event_type: AuditEventType | None = None,
        details: dict[str, object] | None = None,
    ) -> ActionProposal:
        """Move the proposal one state on, with its explanation, in one transaction."""

        changed = proposal.model_copy(
            update={
                "state": state,
                "version": proposal.version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        with self._unit_of_work() as unit:
            unit.proposals.replace(proposal=changed, expected_version=proposal.version)
            if event_type is not None:
                unit.audit.append(
                    AuditEvent(
                        event_type=event_type,
                        tenant_id=changed.tenant_id,
                        actor_user_id=context.user_id,
                        correlation_id=changed.correlation_id,
                        action_proposal_id=changed.id,
                        details={
                            "state": changed.state,
                            "version": changed.version,
                            **(details or {}),
                        },
                    )
                )
            unit.commit()
        return changed
