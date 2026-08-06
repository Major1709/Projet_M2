from threading import RLock
from uuid import UUID

from app.approvals.domain import ActionProposal
from app.approvals.errors import ProposalNotFound, VersionConflict


class InMemoryActionProposalRepository:
    """Development-only repository with atomic optimistic transitions per process."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, UUID], ActionProposal] = {}
        self._lock = RLock()

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
