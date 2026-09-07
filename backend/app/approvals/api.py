from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.agent.mutation_workflow import ApprovedMutationRunner
from app.approvals.domain import (
    ActionDecision,
    ActionProposalCreate,
    ActionProposalCreatedView,
    ActionProposalView,
    ActionRevision,
    ActionRevisionView,
    MutationExecution,
    MutationExecutionView,
)
from app.approvals.errors import (
    ApprovalError,
    InvalidDecisionToken,
    InvalidTransition,
    ProposalConversationNotFound,
    ProposalExpired,
    ProposalNotFound,
    SessionRequired,
    VersionConflict,
)
from app.approvals.workflow import ApprovalWorkflow
from app.core.errors import IDENTITY_RESPONSES, coded, responses_for
from app.core.identity import SecurityContext, get_security_context

router = APIRouter(prefix="/api/actions", tags=["actions"])


def get_workflow(request: Request) -> ApprovalWorkflow:
    return request.app.state.container.approvals


# Which status each failure deserves, as data. The route translates with it and the
# OpenAPI document is generated from it, so the two cannot describe different APIs.
# Ordered most specific first: the first match wins, as an if/elif chain did.
STATUS_BY_ERROR: tuple[tuple[type[ApprovalError], int], ...] = (
    (ProposalNotFound, status.HTTP_404_NOT_FOUND),
    (ProposalConversationNotFound, status.HTTP_404_NOT_FOUND),
    # 410 rather than 409: the window is gone, so retrying this proposal will never
    # succeed. A conflict would invite the client to refetch and try again.
    (ProposalExpired, status.HTTP_410_GONE),
    (InvalidDecisionToken, status.HTTP_409_CONFLICT),
    (InvalidTransition, status.HTTP_409_CONFLICT),
    (VersionConflict, status.HTTP_409_CONFLICT),
    # 401 rather than 400: the request is well formed, and what is missing is a
    # sign-in. A 400 would send the client looking for a bad field.
    (SessionRequired, status.HTTP_401_UNAUTHORIZED),
    # TenantBoundaryViolation is absent deliberately: nothing raises it today, and
    # a contract that describes a failure which cannot happen is a client writing a
    # branch it can never reach. It falls to the 400 default if that ever changes.
)

def _responses(*errors: type[ApprovalError]) -> dict[int | str, dict[str, object]]:
    """The failures one route can really produce, drawn from the single status table.

    Per route rather than one shared set, because a GET that advertises 410 GONE
    invites a branch that can never run -- and a contract wrong in the permissive
    direction still teaches the client something untrue.
    """

    chosen = tuple(pair for pair in STATUS_BY_ERROR if pair[0] in errors)
    return responses_for(chosen, *IDENTITY_RESPONSES)


# Every decision route shares these: the proposal may be gone, the window may have
# closed, the token may be spent, the state or the version may have moved on.
DECIDING = (
    ProposalNotFound,
    ProposalExpired,
    InvalidDecisionToken,
    InvalidTransition,
    VersionConflict,
)
PROPOSE_RESPONSES = _responses(ProposalConversationNotFound, SessionRequired)
GET_RESPONSES = _responses(ProposalNotFound)
DECIDE_RESPONSES = _responses(*DECIDING)
REVISE_RESPONSES = _responses(*DECIDING, ProposalConversationNotFound, SessionRequired)


def translate_domain_error(error: ApprovalError) -> HTTPException:
    for error_type, status_code in STATUS_BY_ERROR:
        if isinstance(error, error_type):
            return coded(status_code, error_type.code, str(error))
    return coded(status.HTTP_400_BAD_REQUEST, error.code, str(error))


@router.post(
    "",
    response_model=ActionProposalCreatedView,
    status_code=status.HTTP_201_CREATED,
    responses=PROPOSE_RESPONSES,
)
def create_action_proposal(
    command: ActionProposalCreate,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ApprovalWorkflow, Depends(get_workflow)],
) -> ActionProposalCreatedView:
    try:
        issued = workflow.propose(command, context)
        return ActionProposalCreatedView(
            **ActionProposalView.from_domain(issued.proposal).model_dump(),
            decision_token=issued.decision_token,
        )
    except ApprovalError as error:
        raise translate_domain_error(error) from error


@router.get("/{proposal_id}", response_model=ActionProposalView, responses=GET_RESPONSES)
def get_action_proposal(
    proposal_id: UUID,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ApprovalWorkflow, Depends(get_workflow)],
) -> ActionProposalView:
    try:
        return ActionProposalView.from_domain(workflow.get(proposal_id, context))
    except ApprovalError as error:
        raise translate_domain_error(error) from error


@router.post(
    "/{proposal_id}/approve",
    response_model=ActionProposalView,
    responses=DECIDE_RESPONSES,
)
def approve_action_proposal(
    proposal_id: UUID,
    decision: ActionDecision,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ApprovalWorkflow, Depends(get_workflow)],
) -> ActionProposalView:
    try:
        return ActionProposalView.from_domain(workflow.approve(proposal_id, decision, context))
    except ApprovalError as error:
        raise translate_domain_error(error) from error


@router.post("/{proposal_id}/reject", response_model=ActionProposalView, responses=DECIDE_RESPONSES)
def reject_action_proposal(
    proposal_id: UUID,
    decision: ActionDecision,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ApprovalWorkflow, Depends(get_workflow)],
) -> ActionProposalView:
    try:
        return ActionProposalView.from_domain(workflow.reject(proposal_id, decision, context))
    except ApprovalError as error:
        raise translate_domain_error(error) from error


@router.post("/{proposal_id}/revise", response_model=ActionRevisionView, responses=REVISE_RESPONSES)
def revise_action_proposal(
    proposal_id: UUID,
    revision: ActionRevision,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ApprovalWorkflow, Depends(get_workflow)],
) -> ActionRevisionView:
    try:
        issued = workflow.revise(proposal_id, revision, context)
        return ActionRevisionView(
            superseded=ActionProposalView.from_domain(issued.superseded),
            replacement=ActionProposalView.from_domain(issued.replacement),
            decision_token=issued.decision_token,
        )
    except ApprovalError as error:
        raise translate_domain_error(error) from error


def get_mutations(request: Request) -> ApprovedMutationRunner:
    """Le chemin d'ecriture, ou un refus de politique s'il n'est pas ouvert.

    403 et non 404, comme la route d'assistant quand aucun modele n'est configure :
    une surface desactivee est une decision de deploiement, et l'annoncer franchement
    vaut mieux que de simuler une absence que le document OpenAPI trahirait de toute
    facon.
    """

    runner = request.app.state.container.mutations
    if runner is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "MCP_MUTATIONS_DISABLED",
                "message": "External writes are not enabled",
            },
        )
    return runner


EXECUTE_RESPONSES = {
    **_responses(
        ProposalNotFound,
        ProposalExpired,
        InvalidTransition,
        VersionConflict,
        SessionRequired,
    ),
    # Deux statuts qu'aucune table de traduction ne produit : l'un vient de la
    # dependance qui refuse une surface desactivee, l'autre d'un appel dont l'issue
    # est inconnue.
    **responses_for(
        (),
        (status.HTTP_403_FORBIDDEN, "MCP_MUTATIONS_DISABLED"),
        (status.HTTP_502_BAD_GATEWAY, "MUTATION_OUTCOME_UNKNOWN"),
    ),
}


@router.post(
    "/{proposal_id}/execute",
    response_model=MutationExecutionView,
    responses=EXECUTE_RESPONSES,
)
def execute_action_proposal(
    proposal_id: UUID,
    command: MutationExecution,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    runner: Annotated[ApprovedMutationRunner, Depends(get_mutations)],
) -> MutationExecutionView:
    """Depenser une approbation.

    ``expected_version`` est exige dans le corps et n'a rien d'une formalite : entre
    le moment ou une interface affiche une proposition et celui ou quelqu'un clique,
    la proposition a pu etre revisee, rejetee ou deja executee. Sans cette version,
    le second clic depenserait une approbation qui n'est plus celle qui a ete
    montree.
    """

    try:
        result = runner.execute(
            proposal_id=proposal_id,
            expected_version=command.expected_version,
            context=context,
        )
    except ApprovalError as error:
        raise translate_domain_error(error) from error
    except Exception as error:
        # L'issue est INCONNUE, et c'est ce que le code doit dire. L'appel est parti
        # et rien n'est revenu : le ticket a peut-etre ete cree. Un 500 laisserait un
        # client conclure a l'echec et reessayer, ce qui creerait le doublon que la
        # reservation d'idempotence existe pour eviter. La reservation reste ouverte
        # exprès -- la reprise honnete represente la meme cle, elle ne recommence pas
        # de zero.
        raise coded(
            status.HTTP_502_BAD_GATEWAY,
            "MUTATION_OUTCOME_UNKNOWN",
            "The write was dispatched and its outcome is unknown; do not retry blindly",
        ) from error

    return MutationExecutionView.from_domain(result)
