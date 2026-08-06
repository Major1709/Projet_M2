"""Public interface of the approval module."""

from app.approvals.domain import (
    ActionDecision,
    ActionProposal,
    ActionProposalCreate,
    ActionProposalState,
    ActionProposalView,
    ActionRevision,
    ActionRevisionView,
    ActionTarget,
)
from app.approvals.errors import InvalidTransition, VersionConflict
from app.approvals.workflow import ApprovalWorkflow

__all__ = [
    "ActionDecision",
    "ActionProposal",
    "ActionProposalCreate",
    "ActionProposalState",
    "ActionProposalView",
    "ActionRevision",
    "ActionRevisionView",
    "ActionTarget",
    "ApprovalWorkflow",
    "InvalidTransition",
    "VersionConflict",
]
