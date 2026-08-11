from threading import RLock
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from app.approvals.domain import ActionProposal
from app.approvals.errors import ProposalNotFound, VersionConflict
from app.audit.adapters.memory import InMemoryAuditSink


class InMemoryActionProposalRepository:
    """Development-only repository with atomic optimistic transitions per process."""

    def __init__(self, *, lock: Any | None = None) -> None:
        self._items: dict[tuple[str, UUID], ActionProposal] = {}
        self._lock = lock if lock is not None else RLock()

    def add(self, proposal: ActionProposal) -> None:
        with self._lock:
            key = (proposal.tenant_id, proposal.id)
            if key in self._items:
                raise ValueError(f"Proposal {proposal.id} already exists")
            self._items[key] = proposal

    def get(self, *, tenant_id: str, proposal_id: UUID) -> ActionProposal | None:
        with self._lock:
            return self._items.get((tenant_id, proposal_id))

    def replace(self, *, proposal: ActionProposal, expected_version: int) -> None:
        with self._lock:
            key = (proposal.tenant_id, proposal.id)
            current = self._items.get(key)
            if current is None:
                raise ProposalNotFound(proposal.id)
            if current.version != expected_version:
                raise VersionConflict(expected=expected_version, actual=current.version)
            if proposal.version != expected_version + 1:
                raise ValueError("Replacement version must increment exactly once")
            self._items[key] = proposal

    def supersede_and_add(
        self,
        *,
        superseded: ActionProposal,
        replacement: ActionProposal,
        expected_version: int,
    ) -> None:
        with self._lock:
            old_key = (superseded.tenant_id, superseded.id)
            current = self._items.get(old_key)
            if current is None:
                raise ProposalNotFound(superseded.id)
            if current.version != expected_version:
                raise VersionConflict(expected=expected_version, actual=current.version)
            if superseded.version != expected_version + 1:
                raise ValueError("Superseded version must increment exactly once")
            new_key = (replacement.tenant_id, replacement.id)
            if replacement.tenant_id != superseded.tenant_id:
                raise ValueError("A revision cannot cross a tenant boundary")
            if new_key in self._items:
                raise ValueError(f"Proposal {replacement.id} already exists")
            self._items[old_key] = superseded
            self._items[new_key] = replacement

    def snapshot(self) -> tuple[ActionProposal, ...]:
        with self._lock:
            return tuple(self._items.values())

    def _snapshot(self) -> dict[tuple[str, UUID], ActionProposal]:
        with self._lock:
            return self._items.copy()

    def _restore(self, items: dict[tuple[str, UUID], ActionProposal]) -> None:
        with self._lock:
            self._items = items.copy()


class _InMemoryApprovalTransaction:
    def __init__(
        self,
        *,
        lock: Any,
        proposals: InMemoryActionProposalRepository,
        audit: InMemoryAuditSink,
    ) -> None:
        self._lock = lock
        self.proposals = proposals
        self.audit = audit
        self._proposal_snapshot: dict[tuple[str, UUID], ActionProposal] | None = None
        self._audit_snapshot = None
        self._committed = False

    def __enter__(self) -> Self:
        self._lock.acquire()
        self._proposal_snapshot = self.proposals._snapshot()
        self._audit_snapshot = self.audit.snapshot()
        self._committed = False
        return self

    def commit(self) -> None:
        if self._proposal_snapshot is None:
            raise RuntimeError("No approval transaction is active")
        self._committed = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        try:
            if exc_type is not None or not self._committed:
                if self._proposal_snapshot is not None:
                    self.proposals._restore(self._proposal_snapshot)
                if self._audit_snapshot is not None:
                    self.audit._restore(self._audit_snapshot)
        finally:
            self._proposal_snapshot = None
            self._audit_snapshot = None
            self._committed = False
            self._lock.release()
        return False


class InMemoryApprovalUnitOfWork:
    """Callable factory sharing one serialized in-memory proposal/audit store."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.proposals = InMemoryActionProposalRepository(lock=self._lock)
        self.audit = InMemoryAuditSink(lock=self._lock)

    def __call__(self) -> _InMemoryApprovalTransaction:
        return _InMemoryApprovalTransaction(
            lock=self._lock,
            proposals=self.proposals,
            audit=self.audit,
        )
