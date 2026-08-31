import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.agent.errors import (
    AgentAuditUnavailable,
    LLMAuditUnavailable,
    LLMCallTimeout,
    LLMCredentialUnavailable,
    LLMDNSRejected,
    LLMError,
    LLMInvalidResponse,
    LLMProviderRefused,
    LLMRateLimited,
    LLMRequestTooLarge,
    LLMResponseTooLarge,
    LLMTransportFailure,
)
from app.agent.read_workflow import AgentAnswer, AgentQuestion, AgentReadWorkflow
from app.conversations.domain import CitedSource, MessageRole, MessageStatus
from app.conversations.errors import ConversationNotFound
from app.conversations.workflow import ConversationWorkflow
from app.core.errors import IDENTITY_RESPONSES, coded, responses_for
from app.core.identity import SecurityContext, get_security_context
from app.mcp.api import translate_read_error
from app.mcp.errors import MCPReadError

router = APIRouter(prefix="/api/agent", tags=["agent"])

logger = logging.getLogger(__name__)


def get_agent(request: Request) -> AgentReadWorkflow:
    agent = request.app.state.container.agent
    if agent is None:
        # 403 rather than 404: the route exists and the deployment has switched the
        # provider off, which is a policy answer. The same code the MCP layer uses
        # for a disabled provider, for the same reason.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "LLM_PROVIDER_DISABLED",
                "message": "No language model provider is enabled",
            },
        )
    return agent


def get_conversations(request: Request) -> ConversationWorkflow:
    return request.app.state.container.conversations


def _cited(answer: AgentAnswer) -> tuple[CitedSource, ...]:
    return tuple(
        CitedSource(
            source_system=source.source_system.value,
            tool_name=source.tool_name,
            resource_reference=source.url,
            retrieved_at=source.retrieved_at,
            truncated=source.truncated,
        )
        for source in answer.sources
    )


def _record(
    conversations: ConversationWorkflow,
    *,
    conversation_id: UUID,
    context: SecurityContext,
    role: MessageRole,
    content: str,
    correlation_id: str,
    status_: MessageStatus = MessageStatus.COMPLETE,
    sources: tuple[CitedSource, ...] = (),
) -> None:
    """Record one turn, and never let that recording sink the exchange.

    Deliberately not fail-closed, unlike the audit trail, because the two protect
    different things: an unrecorded read is a governance hole, while an unsaved line
    of conversation is an inconvenience. Refusing an answer that already cost a
    model call and a real read, because history could not be written, would destroy
    more than it protects -- and the audit trail still holds the full account.
    """

    try:
        conversations.append_message(
            conversation_id=conversation_id,
            context=context,
            role=role,
            content=content,
            correlation_id=correlation_id,
            status=status_,
            sources=sources,
        )
    except Exception as error:  # noqa: BLE001 - history must never fail the answer
        logger.warning(
            "conversation turn not recorded",
            extra={
                "correlation_id": correlation_id,
                "role": role.value,
                "error_type": type(error).__name__,
            },
        )


# Beside the chain below, and the source of the documented responses, so a new
# LLM failure cannot be handled at runtime while staying absent from the contract.
STATUS_BY_ERROR: tuple[tuple[type[Exception], int], ...] = (
    (AgentAuditUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
    (LLMAuditUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
    (LLMCredentialUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
    (LLMRateLimited, status.HTTP_429_TOO_MANY_REQUESTS),
    (LLMRequestTooLarge, status.HTTP_413_CONTENT_TOO_LARGE),
    (LLMCallTimeout, status.HTTP_504_GATEWAY_TIMEOUT),
    (LLMDNSRejected, status.HTTP_502_BAD_GATEWAY),
    (LLMTransportFailure, status.HTTP_502_BAD_GATEWAY),
    (LLMProviderRefused, status.HTTP_502_BAD_GATEWAY),
    (LLMInvalidResponse, status.HTTP_502_BAD_GATEWAY),
    (LLMResponseTooLarge, status.HTTP_502_BAD_GATEWAY),
)

ERROR_RESPONSES = responses_for(
    STATUS_BY_ERROR,
    *IDENTITY_RESPONSES,
    (status.HTTP_403_FORBIDDEN, "LLM_PROVIDER_DISABLED"),
    (status.HTTP_404_NOT_FOUND, ConversationNotFound.code),
)


def translate_llm_error(error: LLMError) -> HTTPException:
    if isinstance(
        error, (AgentAuditUnavailable, LLMAuditUnavailable, LLMCredentialUnavailable)
    ):
        # Nothing the caller can fix and nothing that retrying now will resolve, but
        # the deployment can: an operator restores the trail or the credential.
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, LLMRateLimited):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(error, LLMRequestTooLarge):
        # 413 rather than 429 even though the provider labels the cause a rate
        # limit: waiting does not help, the request has to get smaller.
        status_code = status.HTTP_413_CONTENT_TOO_LARGE
    elif isinstance(error, LLMCallTimeout):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    elif isinstance(
        error,
        (
            LLMDNSRejected,
            LLMTransportFailure,
            LLMProviderRefused,
            LLMInvalidResponse,
            LLMResponseTooLarge,
        ),
    ):
        status_code = status.HTTP_502_BAD_GATEWAY
    else:  # pragma: no cover - defensive mapping for future safe errors
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.safe_message},
    )


@router.post("/questions", response_model=AgentAnswer, responses=ERROR_RESPONSES)
async def answer_question(
    question: AgentQuestion,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    agent: Annotated[AgentReadWorkflow, Depends(get_agent)],
    conversations: Annotated[ConversationWorkflow, Depends(get_conversations)],
) -> AgentAnswer:
    thread = question.conversation_id
    if thread is not None:
        # Proven before the model is called, not after: spending a call to then
        # discover the thread is someone else's would waste a real budget, and the
        # 404 is the honest answer either way.
        try:
            conversations.get(thread, context)
        except ConversationNotFound as error:
            raise coded(
                status.HTTP_404_NOT_FOUND,
                ConversationNotFound.code,
                "Conversation not found",
            ) from error
        # Written first, so a question survives a provider refusal. A turn with no
        # answer beside it describes exactly what happened.
        _record(
            conversations,
            conversation_id=thread,
            context=context,
            role=MessageRole.USER,
            content=question.question,
            correlation_id=question.correlation_id,
        )

    try:
        answer = await agent.answer(question=question, context=context)
    except LLMError as error:
        raise translate_llm_error(error) from error
    except MCPReadError as error:
        # A read refusal the loop judged fatal. Translated by the MCP layer's own
        # table so one cause keeps one status code whether it is reached directly
        # or through the assistant.
        raise translate_read_error(error) from error

    if thread is not None:
        _record(
            conversations,
            conversation_id=thread,
            context=context,
            role=MessageRole.ASSISTANT,
            content=answer.text,
            correlation_id=question.correlation_id,
            sources=_cited(answer),
        )
    return answer
