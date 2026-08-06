import hmac
from datetime import UTC, datetime
from uuid import UUID

from app.approvals.domain import (
    ActionDecision,
    ActionProposal,
    ActionProposalCreate,
    ActionProposalState,
    ActionRevision,
)
from app.approvals.errors import (
    InvalidDecisionToken,
    InvalidTransition,
    ProposalNotFound,
    VersionConflict,
)
from app.approvals.ports import ApprovalRepository
from app.audit.domain import AuditEvent, AuditEventType
from app.audit.ports import AuditSink
from app.core.identity import SecurityContext, security_context_fingerprint


class ApprovalWorkflow:
    """Owns proposal snapshots, decisions, revisions and their audit trail."""

    def __init__(self, repository: ApprovalRepository, audit_sink: AuditSink) -> None:
        self._repository = repository
        self._audit_sink = audit_sink

    def propose(self, command: ActionProposalCreate, context: SecurityContext) -> ActionProposal:
        proposal = ActionProposal.from_command(
            command=command,
            tenant_id=context.tenant_id,
            proposed_by_user_id=context.user_id,
            execution_context_hash=security_context_fingerprint(context),
        )
        self._repository.add(proposal)
        self._audit(proposal, context.user_id, AuditEventType.ACTION_PROPOSED)
        return proposal

    def get(self, proposal_id: UUID, context: SecurityContext) -> ActionProposal:
        proposal = self._repository.get(
            tenant_id=context.tenant_id,
            proposal_id=proposal_id,
        )
        if proposal is None:
            raise ProposalNotFound(proposal_id)
        # TODO(IAM): Replace owner-only access with an authorization policy that
        # supports nominated reviewers without exposing payloads tenant-wide.
        if proposal.proposed_by_user_id != context.user_id:
            raise ProposalNotFound(proposal_id)
        return proposal

    def approve(
        self,
        proposal_id: UUID,
        decision: ActionDecision,
        context: SecurityContext,
    ) -> ActionProposal:
        current = self.get(proposal_id, context)
        self._validate_decision(current, decision)
        approved = current.model_copy(
            update={
                "state": ActionProposalState.APPROVED,
                "version": current.version + 1,
                "decision_token": None,
                "approved_by_user_id": context.user_id,
                "decision_reason": decision.reason,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.replace(proposal=approved, expected_version=decision.expected_version)
        self._audit(approved, context.user_id, AuditEventType.ACTION_APPROVED)
        return approved

    def reject(
        self,
        proposal_id: UUID,
        decision: ActionDecision,
        context: SecurityContext,
    ) -> ActionProposal:
        current = self.get(proposal_id, context)
        self._validate_decision(current, decision)
        rejected = current.model_copy(
            update={
                "state": ActionProposalState.REJECTED,
                "version": current.version + 1,
                "decision_token": None,
                "decision_reason": decision.reason,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.replace(proposal=rejected, expected_version=decision.expected_version)
        self._audit(rejected, context.user_id, AuditEventType.ACTION_REJECTED)
        return rejected

    def revise(
        self,
        proposal_id: UUID,
        revision: ActionRevision,
        context: SecurityContext,
    ) -> tuple[ActionProposal, ActionProposal]:
        current = self.get(proposal_id, context)
        decision = ActionDecision(
            expected_version=revision.expected_version,
            decision_token=revision.decision_token,
            reason=revision.reason,
        )
        self._validate_decision(current, decision)

        replacement_command = ActionProposalCreate(
            conversation_id=current.conversation_id,
            source_system=current.source_system,
            tool_name=current.tool_name,
            action_class=current.action_class,
            target=revision.target,
            payload=revision.payload,
            explanation=revision.explanation,
            diff=revision.diff,
            correlation_id=current.correlation_id,
        )
        replacement = ActionProposal.from_command(
            command=replacement_command,
            tenant_id=current.tenant_id,
            proposed_by_user_id=context.user_id,
            execution_context_hash=security_context_fingerprint(context),
            supersedes_id=current.id,
        )
        superseded = current.model_copy(
            update={
                "state": ActionProposalState.SUPERSEDED,
                "version": current.version + 1,
                "decision_token": None,
                "decision_reason": revision.reason,
                "updated_at": datetime.now(UTC),
            }
        )
        self._repository.supersede_and_add(
            superseded=superseded,
            replacement=replacement,
            expected_version=revision.expected_version,
        )
        self._audit(superseded, context.user_id, AuditEventType.ACTION_REVISED)
        self._audit(replacement, context.user_id, AuditEventType.ACTION_PROPOSED)
        return superseded, replacement

    @staticmethod
    def _validate_decision(proposal: ActionProposal, decision: ActionDecision) -> None:
        if proposal.state != ActionProposalState.PENDING_APPROVAL:
            raise InvalidTransition(
                f"Only PENDING_APPROVAL can receive a decision, got {proposal.state}"
            )
        if proposal.version != decision.expected_version:
            raise VersionConflict(expected=decision.expected_version, actual=proposal.version)
        if proposal.decision_token is None or not hmac.compare_digest(
            proposal.decision_token,
            decision.decision_token,
        ):
            raise InvalidDecisionToken("The decision token is invalid or already consumed")

    def _audit(
        self,
        proposal: ActionProposal,
        actor_user_id: str,
        event_type: AuditEventType,
    ) -> None:
        self._audit_sink.append(
            AuditEvent(
                event_type=event_type,
                tenant_id=proposal.tenant_id,
                actor_user_id=actor_user_id,
                correlation_id=proposal.correlation_id,
                action_proposal_id=proposal.id,
                details={
                    "state": proposal.state,
                    "version": proposal.version,
                    "source_system": proposal.source_system,
                    "tool_name": proposal.tool_name,
                    "action_class": proposal.action_class,
                    "payload_hash": proposal.payload_hash,
                },
            )
        )
