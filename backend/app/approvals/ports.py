from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.approvals.domain import ActionProposal
from app.audit.ports import AuditSink


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
