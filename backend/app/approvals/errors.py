from uuid import UUID


class ApprovalError(Exception):
    """Base class for safe approval-domain errors.

    Every subclass carries a stable ``code``. It is what a client branches on, and
    it is what the route hands back -- the message beside it may be reworded or
    translated without anyone's code breaking.
    """

    code = "APPROVAL_ERROR"


class ProposalNotFound(ApprovalError):
    code = "PROPOSAL_NOT_FOUND"

    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(f"Action proposal {proposal_id} was not found")


class ProposalConversationNotFound(ApprovalError):
    code = "CONVERSATION_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Conversation not found")


class VersionConflict(ApprovalError):
    code = "VERSION_CONFLICT"

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(f"Expected proposal version {expected}, current version is {actual}")
        self.expected = expected
        self.actual = actual


class InvalidTransition(ApprovalError):
    code = "INVALID_TRANSITION"


class InvalidDecisionToken(ApprovalError):
    code = "INVALID_DECISION_TOKEN"


class TenantBoundaryViolation(ApprovalError):
    code = "TENANT_BOUNDARY_VIOLATION"


class ProposalExpired(ApprovalError):
    """The approval window closed before the decision or the execution arrived."""

    code = "PROPOSAL_EXPIRED"


class SessionRequired(ApprovalError):
    """A mutation was proposed from an identity no sign-in stands behind.

    Named rather than folded into InvalidTransition: nothing about the proposal is
    wrong, and no change to the payload would fix it. The deployment is deriving
    identities from headers, so there is no session for the consent to end with.
    """

    code = "SESSION_REQUIRED"
