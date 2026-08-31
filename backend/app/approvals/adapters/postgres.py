from json import JSONDecodeError
from types import TracebackType
from typing import Self
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.approvals.domain import ActionProposal
from app.approvals.errors import ProposalNotFound, VersionConflict
from app.audit.adapters.postgres import PostgresAuditSink
from app.persistence.errors import PersistenceMappingError
from app.persistence.schema import action_proposals


def _proposal_values(proposal: ActionProposal) -> dict[str, object]:
    return {
        "tenant_id": proposal.tenant_id,
        "id": proposal.id,
        "conversation_id": proposal.conversation_id,
        "proposed_by_user_id": proposal.proposed_by_user_id,
        "source_system": proposal.source_system.value,
        "tool_name": proposal.tool_name,
        "action_class": proposal.action_class.value,
        "target": proposal.target.model_dump(mode="json"),
        "payload_json": proposal.payload_json,
        "payload_hash": proposal.payload_hash,
        "explanation": proposal.explanation,
        "diff_json": proposal.diff_json,
        "correlation_id": proposal.correlation_id,
        "execution_context_hash": proposal.execution_context_hash,
        "tool_schema_sha256": proposal.tool_schema_sha256,
        "expires_at": proposal.expires_at,
        "state": proposal.state.value,
        "version": proposal.version,
        "decision_token_hash": proposal.decision_token_hash,
        "supersedes_id": proposal.supersedes_id,
        "approved_by_user_id": proposal.approved_by_user_id,
        "decision_reason": proposal.decision_reason,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }


def _map_proposal(row: dict[str, object]) -> ActionProposal:
    try:
        proposal = ActionProposal.model_validate(row)
        if not isinstance(proposal.payload, dict):
            raise TypeError
        if proposal.diff is not None and not isinstance(proposal.diff, dict):
            raise TypeError
        return proposal
    except (JSONDecodeError, TypeError, ValidationError):
        raise PersistenceMappingError("Stored action proposal is invalid") from None


class PostgresActionProposalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, proposal: ActionProposal) -> None:
        self._session.execute(insert(action_proposals).values(**_proposal_values(proposal)))

    def get(self, *, tenant_id: str, proposal_id: UUID) -> ActionProposal | None:
        statement = select(action_proposals).where(
            action_proposals.c.tenant_id == tenant_id,
            action_proposals.c.id == proposal_id,
        )
        row = self._session.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        return _map_proposal(dict(row))

    def replace(self, *, proposal: ActionProposal, expected_version: int) -> None:
        if proposal.version != expected_version + 1:
            raise ValueError("Replacement version must increment exactly once")

        values = _proposal_values(proposal)
        values.pop("tenant_id")
        values.pop("id")
        statement = (
            update(action_proposals)
            .where(
                action_proposals.c.tenant_id == proposal.tenant_id,
                action_proposals.c.id == proposal.id,
                action_proposals.c.version == expected_version,
            )
            .values(**values)
        )
        result = self._session.execute(statement)
        if result.rowcount == 1:
            return

        current_version = self._session.execute(
            select(action_proposals.c.version).where(
                action_proposals.c.tenant_id == proposal.tenant_id,
                action_proposals.c.id == proposal.id,
            )
        ).scalar_one_or_none()
        if current_version is None:
            raise ProposalNotFound(proposal.id)
        raise VersionConflict(expected=expected_version, actual=current_version)

    def supersede_and_add(
        self,
        *,
        superseded: ActionProposal,
        replacement: ActionProposal,
        expected_version: int,
    ) -> None:
        if replacement.tenant_id != superseded.tenant_id:
            raise ValueError("A revision cannot cross a tenant boundary")
        self.replace(proposal=superseded, expected_version=expected_version)
        self.add(replacement)


class PostgresApprovalUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._committed = False

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.proposals = PostgresActionProposalRepository(self._session)
        self.audit = PostgresAuditSink(self._session)
        self._committed = False
        return self

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("No approval transaction is active")
        self._session.commit()
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        if self._session is None:
            return False
        try:
            if exc_type is not None or not self._committed:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
            self._committed = False
        return False


class PostgresApprovalUnitOfWorkFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> PostgresApprovalUnitOfWork:
        return PostgresApprovalUnitOfWork(self._session_factory)
