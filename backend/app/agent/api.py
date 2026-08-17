from typing import Annotated

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
from app.core.identity import SecurityContext, get_development_security_context
from app.mcp.api import translate_read_error
from app.mcp.errors import MCPReadError

router = APIRouter(prefix="/api/agent", tags=["agent"])


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


@router.post("/questions", response_model=AgentAnswer)
async def answer_question(
    question: AgentQuestion,
    context: Annotated[SecurityContext, Depends(get_development_security_context)],
    agent: Annotated[AgentReadWorkflow, Depends(get_agent)],
) -> AgentAnswer:
    try:
        return await agent.answer(question=question, context=context)
    except LLMError as error:
        raise translate_llm_error(error) from error
    except MCPReadError as error:
        # A read refusal the loop judged fatal. Translated by the MCP layer's own
        # table so one cause keeps one status code whether it is reached directly
        # or through the assistant.
        raise translate_read_error(error) from error
