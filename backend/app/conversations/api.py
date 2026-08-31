from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.conversations.domain import (
    Conversation,
    ConversationCreate,
    ConversationMessage,
)
from app.conversations.errors import ConversationNotFound
from app.conversations.workflow import MAX_MESSAGES_RETURNED, ConversationWorkflow
from app.core.errors import IDENTITY_RESPONSES, coded, responses_for
from app.core.identity import SecurityContext, get_security_context

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

NOT_FOUND: tuple[tuple[type[Exception], int], ...] = (
    (ConversationNotFound, status.HTTP_404_NOT_FOUND),
)
ERROR_RESPONSES = responses_for(NOT_FOUND, *IDENTITY_RESPONSES)


def get_workflow(request: Request) -> ConversationWorkflow:
    return request.app.state.container.conversations


@router.post(
    "",
    response_model=Conversation,
    status_code=status.HTTP_201_CREATED,
    responses=responses_for((), *IDENTITY_RESPONSES),
)
def create_conversation(
    command: ConversationCreate,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ConversationWorkflow, Depends(get_workflow)],
) -> Conversation:
    return workflow.create(command, context)


@router.get("/{conversation_id}", response_model=Conversation, responses=ERROR_RESPONSES)
def get_conversation(
    conversation_id: UUID,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ConversationWorkflow, Depends(get_workflow)],
) -> Conversation:
    try:
        return workflow.get(conversation_id, context)
    except ConversationNotFound as error:
        raise coded(
            status.HTTP_404_NOT_FOUND,
            ConversationNotFound.code,
            "Conversation not found",
        ) from error


@router.get(
    "/{conversation_id}/messages",
    response_model=list[ConversationMessage],
    responses=ERROR_RESPONSES,
)
def list_conversation_messages(
    conversation_id: UUID,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[ConversationWorkflow, Depends(get_workflow)],
    limit: Annotated[int, Query(ge=1, le=MAX_MESSAGES_RETURNED)] = MAX_MESSAGES_RETURNED,
) -> list[ConversationMessage]:
    try:
        return list(workflow.list_messages(conversation_id, context, limit))
    except ConversationNotFound as error:
        # The same 404 the thread itself returns. A conversation belonging to another
        # user must not be distinguishable from one that does not exist, or the
        # status code becomes a way to enumerate what other people have.
        raise coded(
            status.HTTP_404_NOT_FOUND,
            ConversationNotFound.code,
            "Conversation not found",
        ) from error
