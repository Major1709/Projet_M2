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


class ProposalExpired(ApprovalError):
    """The approval window closed before the decision or the execution arrived."""


class SessionRequired(ApprovalError):
    """A mutation was proposed from an identity no sign-in stands behind.

    Named rather than folded into InvalidTransition: nothing about the proposal is
    wrong, and no change to the payload would fix it. The deployment is deriving
    identities from headers, so there is no session for the consent to end with.
    """
