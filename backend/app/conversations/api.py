from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.conversations.domain import (
    Conversation,
    ConversationCreate,
    ConversationMessage,
)
from app.conversations.errors import ConversationNotFound
from app.conversations.workflow import MAX_MESSAGES_RETURNED, ConversationWorkflow
from app.core.identity import SecurityContext, get_development_security_context

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def get_workflow(request: Request) -> ConversationWorkflow:
    return request.app.state.container.conversations


@router.post("", response_model=Conversation, status_code=status.HTTP_201_CREATED)
def create_conversation(
    command: ConversationCreate,
    context: Annotated[SecurityContext, Depends(get_development_security_context)],
    workflow: Annotated[ConversationWorkflow, Depends(get_workflow)],
) -> Conversation:
    return workflow.create(command, context)


@router.get("/{conversation_id}", response_model=Conversation)
def get_conversation(
    conversation_id: UUID,
    context: Annotated[SecurityContext, Depends(get_development_security_context)],
    workflow: Annotated[ConversationWorkflow, Depends(get_workflow)],
) -> Conversation:
    try:
        return workflow.get(conversation_id, context)
    except ConversationNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from error


@router.get("/{conversation_id}/messages", response_model=list[ConversationMessage])
def list_conversation_messages(
    conversation_id: UUID,
    context: Annotated[SecurityContext, Depends(get_development_security_context)],
    workflow: Annotated[ConversationWorkflow, Depends(get_workflow)],
    limit: Annotated[int, Query(ge=1, le=MAX_MESSAGES_RETURNED)] = MAX_MESSAGES_RETURNED,
) -> list[ConversationMessage]:
    try:
        return list(workflow.list_messages(conversation_id, context, limit))
    except ConversationNotFound as error:
        # The same 404 the thread itself returns. A conversation belonging to another
        # user must not be distinguishable from one that does not exist, or the
        # status code becomes a way to enumerate what other people have.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from error
