from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.approvals.domain import (
    ActionDecision,
    ActionProposalCreate,
    ActionProposalCreatedView,
    ActionProposalView,
    ActionRevision,
    ActionRevisionView,
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
from app.core.identity import SecurityContext, get_security_context

router = APIRouter(prefix="/api/actions", tags=["actions"])


def get_workflow(request: Request) -> ApprovalWorkflow:
    return request.app.state.container.approvals


def translate_domain_error(error: ApprovalError) -> HTTPException:
    if isinstance(error, (ProposalNotFound, ProposalConversationNotFound)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ProposalExpired):
        # 410 rather than 409: the window is gone, so retrying this proposal will never
        # succeed. A conflict would invite the client to refetch and try again.
        return HTTPException(status_code=status.HTTP_410_GONE, detail=str(error))
    if isinstance(error, InvalidDecisionToken):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, (InvalidTransition, VersionConflict)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, SessionRequired):
        # 401 rather than 400: the request is well formed, and what is missing is a
        # sign-in. A 400 would send the client looking for a bad field.
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("", response_model=ActionProposalCreatedView, status_code=status.HTTP_201_CREATED)
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


@router.get("/{proposal_id}", response_model=ActionProposalView)
def get_action_proposal(
    proposal_id: UUID,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ApprovalWorkflow, Depends(get_workflow)],
) -> ActionProposalView:
    try:
        return ActionProposalView.from_domain(workflow.get(proposal_id, context))
    except ApprovalError as error:
        raise translate_domain_error(error) from error


@router.post("/{proposal_id}/approve", response_model=ActionProposalView)
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


@router.post("/{proposal_id}/reject", response_model=ActionProposalView)
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


@router.post("/{proposal_id}/revise", response_model=ActionRevisionView)
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
