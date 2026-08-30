from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.approvals.domain import ActionProposal
from app.audit.ports import AuditSink
from app.mcp.domain import SourceSystem


class ApprovalRepository(Protocol):
    def add(self, proposal: ActionProposal) -> None: ...

    def get(self, *, tenant_id: str, proposal_id: UUID) -> ActionProposal | None: ...

    def replace(
        self,
        *,
        proposal: ActionProposal,
        expected_version: int,
    ) -> None: ...

    def supersede_and_add(
        self,
        *,
        superseded: ActionProposal,
        replacement: ActionProposal,
        expected_version: int,
    ) -> None: ...


class ApprovalUnitOfWork(Protocol):
    proposals: ApprovalRepository
    audit: AuditSink

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class ApprovalUnitOfWorkFactory(Protocol):
    def __call__(self) -> ApprovalUnitOfWork: ...


class MutationToolPin(Protocol):
    """Resolves the provider schema fingerprint a mutation proposal is bound to.

    Server-derived on purpose: the fingerprint says which tool shape the human was
    shown, so it cannot come from the caller or the model. Implementations deny by
    default -- an unknown tool has no fingerprint and therefore no proposal.
    """

    def schema_sha256(self, *, source_system: SourceSystem, tool_name: str) -> str: ...
