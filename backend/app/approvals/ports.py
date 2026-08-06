from typing import Protocol
from uuid import UUID

from app.approvals.domain import ActionProposal


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
