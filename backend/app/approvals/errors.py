from uuid import UUID


class ApprovalError(Exception):
    """Base class for safe approval-domain errors."""


class ProposalNotFound(ApprovalError):
    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(f"Action proposal {proposal_id} was not found")


class ProposalConversationNotFound(ApprovalError):
    def __init__(self) -> None:
        super().__init__("Conversation not found")


class VersionConflict(ApprovalError):
    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(f"Expected proposal version {expected}, current version is {actual}")
        self.expected = expected
        self.actual = actual


class InvalidTransition(ApprovalError):
    pass


class InvalidDecisionToken(ApprovalError):
    pass


class TenantBoundaryViolation(ApprovalError):
    pass

