import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.approvals.domain import (
    ActionDecision,
    ActionProposal,
    ActionProposalCreate,
    ActionProposalState,
    ActionRevision,
    sha256_text,
)
from app.approvals.errors import (
    InvalidDecisionToken,
    InvalidTransition,
    ProposalConversationNotFound,
    ProposalNotFound,
    VersionConflict,
)
from app.approvals.ports import ApprovalRepository, ApprovalUnitOfWorkFactory
from app.audit.domain import AuditEvent, AuditEventType
from app.audit.ports import AuditSink
from app.conversations.ports import ConversationRepository
from app.core.identity import SecurityContext, security_context_fingerprint


@dataclass(frozen=True, slots=True)
class IssuedActionProposal:
    proposal: ActionProposal
    decision_token: str


@dataclass(frozen=True, slots=True)
class IssuedActionRevision:
    superseded: ActionProposal
    replacement: ActionProposal
    decision_token: str


class ApprovalWorkflow:
    """Owns proposal snapshots, decisions, revisions and their audit trail."""

    def __init__(
        self,
        unit_of_work_factory: ApprovalUnitOfWorkFactory,
        conversation_repository: ConversationRepository,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._conversations = conversation_repository

    def propose(
        self,
        command: ActionProposalCreate,
        context: SecurityContext,
    ) -> IssuedActionProposal:
        self._require_owned_conversation(command.conversation_id, context)
        decision_token = secrets.token_urlsafe(32)
        proposal = ActionProposal.from_command(
            command=command,
            tenant_id=context.tenant_id,
            proposed_by_user_id=context.user_id,
            execution_context_hash=security_context_fingerprint(context),
            decision_token_hash=sha256_text(decision_token),
        )
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.proposals.add(proposal)
            self._audit(
                unit_of_work.audit,
                proposal,
                context.user_id,
                AuditEventType.ACTION_PROPOSED,
            )
            unit_of_work.commit()
        return IssuedActionProposal(proposal=proposal, decision_token=decision_token)

    def get(self, proposal_id: UUID, context: SecurityContext) -> ActionProposal:
        with self._unit_of_work_factory() as unit_of_work:
            return self._get_owned(unit_of_work.proposals, proposal_id, context)

    def approve(
        self,
        proposal_id: UUID,
        decision: ActionDecision,
        context: SecurityContext,
    ) -> ActionProposal:
        with self._unit_of_work_factory() as unit_of_work:
            current = self._get_owned(unit_of_work.proposals, proposal_id, context)
            self._validate_decision(current, decision)
            approved = current.model_copy(
                update={
                    "state": ActionProposalState.APPROVED,
                    "version": current.version + 1,
                    "decision_token_hash": None,
                    "approved_by_user_id": context.user_id,
                    "decision_reason": decision.reason,
                    "updated_at": datetime.now(UTC),
                }
            )
            unit_of_work.proposals.replace(
                proposal=approved,
                expected_version=decision.expected_version,
            )
            self._audit(
                unit_of_work.audit,
                approved,
                context.user_id,
                AuditEventType.ACTION_APPROVED,
            )
            unit_of_work.commit()
        return approved

    def reject(
        self,
        proposal_id: UUID,
        decision: ActionDecision,
        context: SecurityContext,
    ) -> ActionProposal:
        with self._unit_of_work_factory() as unit_of_work:
            current = self._get_owned(unit_of_work.proposals, proposal_id, context)
            self._validate_decision(current, decision)
            rejected = current.model_copy(
                update={
                    "state": ActionProposalState.REJECTED,
                    "version": current.version + 1,
                    "decision_token_hash": None,
                    "decision_reason": decision.reason,
                    "updated_at": datetime.now(UTC),
                }
            )
            unit_of_work.proposals.replace(
                proposal=rejected,
                expected_version=decision.expected_version,
            )
            self._audit(
                unit_of_work.audit,
                rejected,
                context.user_id,
                AuditEventType.ACTION_REJECTED,
            )
            unit_of_work.commit()
        return rejected

    def revise(
        self,
        proposal_id: UUID,
        revision: ActionRevision,
        context: SecurityContext,
    ) -> IssuedActionRevision:
        with self._unit_of_work_factory() as unit_of_work:
            current = self._get_owned(unit_of_work.proposals, proposal_id, context)
            decision = ActionDecision(
                expected_version=revision.expected_version,
                decision_token=revision.decision_token,
                reason=revision.reason,
            )
            self._validate_decision(current, decision)
            self._require_owned_conversation(current.conversation_id, context)

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
            decision_token = secrets.token_urlsafe(32)
            replacement = ActionProposal.from_command(
                command=replacement_command,
                tenant_id=current.tenant_id,
                proposed_by_user_id=context.user_id,
                execution_context_hash=security_context_fingerprint(context),
                decision_token_hash=sha256_text(decision_token),
                supersedes_id=current.id,
            )
            superseded = current.model_copy(
                update={
                    "state": ActionProposalState.SUPERSEDED,
                    "version": current.version + 1,
                    "decision_token_hash": None,
                    "decision_reason": revision.reason,
                    "updated_at": datetime.now(UTC),
                }
            )
            unit_of_work.proposals.supersede_and_add(
                superseded=superseded,
                replacement=replacement,
                expected_version=revision.expected_version,
            )
            self._audit(
                unit_of_work.audit,
                superseded,
                context.user_id,
                AuditEventType.ACTION_REVISED,
            )
            self._audit(
                unit_of_work.audit,
                replacement,
                context.user_id,
                AuditEventType.ACTION_PROPOSED,
            )
            unit_of_work.commit()
        return IssuedActionRevision(
            superseded=superseded,
            replacement=replacement,
            decision_token=decision_token,
        )

    def _require_owned_conversation(
        self,
        conversation_id: UUID,
        context: SecurityContext,
    ) -> None:
        conversation = self._conversations.get(
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
        )
        if conversation is None or conversation.owner_user_id != context.user_id:
            raise ProposalConversationNotFound

    @staticmethod
    def _get_owned(
        repository: ApprovalRepository,
        proposal_id: UUID,
        context: SecurityContext,
    ) -> ActionProposal:
        proposal = repository.get(
            tenant_id=context.tenant_id,
            proposal_id=proposal_id,
        )
        if proposal is None or proposal.proposed_by_user_id != context.user_id:
            raise ProposalNotFound(proposal_id)
        return proposal

    @staticmethod
    def _validate_decision(proposal: ActionProposal, decision: ActionDecision) -> None:
        if proposal.state != ActionProposalState.PENDING_APPROVAL:
            raise InvalidTransition(
                f"Only PENDING_APPROVAL can receive a decision, got {proposal.state}"
            )
        if proposal.version != decision.expected_version:
            raise VersionConflict(expected=decision.expected_version, actual=proposal.version)
        supplied_hash = sha256_text(decision.decision_token)
        if proposal.decision_token_hash is None or not hmac.compare_digest(
            proposal.decision_token_hash,
            supplied_hash,
        ):
            raise InvalidDecisionToken("The decision token is invalid or already consumed")

    @staticmethod
    def _audit(
        audit_sink: AuditSink,
        proposal: ActionProposal,
        actor_user_id: str,
        event_type: AuditEventType,
    ) -> None:
        audit_sink.append(
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
