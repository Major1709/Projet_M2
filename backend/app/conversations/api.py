from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.conversations.domain import Conversation, ConversationCreate
from app.conversations.errors import ConversationNotFound
from app.conversations.workflow import ConversationWorkflow
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
