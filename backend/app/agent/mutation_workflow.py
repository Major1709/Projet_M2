from datetime import UTC, datetime
from uuid import UUID

from app.approvals.domain import ActionProposal, ActionProposalState
from app.approvals.errors import InvalidTransition
from app.approvals.ports import ApprovalRepository
from app.audit.domain import AuditEvent, AuditEventType
from app.audit.ports import AuditSink
from app.core.identity import SecurityContext, security_context_fingerprint
from app.mcp.domain import MCPExecutionResult, MCPToolCall, PermissionCheck
from app.mcp.ports import MCPToolGateway, SourcePermissionVerifier


class ApprovedMutationRunner:
    """Fail-closed mutation façade enforcing approval and source reauthorization."""

    def __init__(
        self,
        *,
        repository: ApprovalRepository,
        gateway: MCPToolGateway,
        permission_verifier: SourcePermissionVerifier,
        audit_sink: AuditSink,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._permission_verifier = permission_verifier
        self._audit_sink = audit_sink

    def execute(
        self,
        *,
        proposal_id: UUID,
        expected_version: int,
        context: SecurityContext,
        idempotency_key: str,
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

        call = MCPToolCall(
            source_system=proposal.source_system,
            tool_name=proposal.tool_name,
            action_class=proposal.action_class,
            arguments=proposal.payload,
            correlation_id=proposal.correlation_id,
        )
        checking = self._transition(proposal, ActionProposalState.PERMISSION_CHECK)
        decision = self._permission_verifier.check(
            PermissionCheck(context=context, call=call)
        )
        self._audit(
            checking,
            context,
            AuditEventType.MUTATION_PERMISSION_CHECKED,
            {"allowed": decision.allowed, "decision_id": decision.decision_id},
        )
        if not decision.allowed:
            self._transition(checking, ActionProposalState.DENIED)
            return MCPExecutionResult(
                succeeded=False,
                error_code=decision.reason_code or "SOURCE_PERMISSION_DENIED",
                safe_message="The source system denied this action",
            )

        executing = self._transition(checking, ActionProposalState.EXECUTING)
        try:
            result = self._gateway.execute_mutation(
                call=call,
                context=context,
                idempotency_key=idempotency_key,
            )
        except Exception:
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
