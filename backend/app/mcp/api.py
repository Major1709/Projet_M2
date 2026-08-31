from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.errors import IDENTITY_RESPONSES, responses_for
from app.core.identity import SecurityContext, get_security_context
from app.mcp.domain import MCPReadBatch, MCPReadBatchResult
from app.mcp.errors import (
    MCPAuditUnavailable,
    MCPBindingUnavailable,
    MCPCallTimeout,
    MCPDNSRejected,
    MCPGrantUnavailable,
    MCPInputRejected,
    MCPInvalidResponse,
    MCPProtocolRejected,
    MCPProviderDisabled,
    MCPRateLimited,
    MCPReadError,
    MCPRemoteToolFailure,
    MCPResponseTooLarge,
    MCPSchemaRejected,
    MCPToolDenied,
    MCPTransportFailure,
)
from app.mcp.read_workflow import MCPReadWorkflow

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# The status each read failure deserves, as data beside the chain that applies it.
# Listed here rather than typed into ``responses=`` so a new error in the taxonomy
# shows up in the API document instead of being silently undocumented.
STATUS_BY_ERROR: tuple[tuple[type[MCPReadError], int], ...] = (
    (MCPToolDenied, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (MCPInputRejected, status.HTTP_422_UNPROCESSABLE_CONTENT),
    (MCPProviderDisabled, status.HTTP_403_FORBIDDEN),
    (MCPAuditUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
    (MCPBindingUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
    (MCPGrantUnavailable, status.HTTP_503_SERVICE_UNAVAILABLE),
    (MCPRateLimited, status.HTTP_429_TOO_MANY_REQUESTS),
    (MCPCallTimeout, status.HTTP_504_GATEWAY_TIMEOUT),
    (MCPProtocolRejected, status.HTTP_502_BAD_GATEWAY),
    (MCPDNSRejected, status.HTTP_502_BAD_GATEWAY),
    (MCPSchemaRejected, status.HTTP_502_BAD_GATEWAY),
    (MCPTransportFailure, status.HTTP_502_BAD_GATEWAY),
    (MCPRemoteToolFailure, status.HTTP_502_BAD_GATEWAY),
    (MCPInvalidResponse, status.HTTP_502_BAD_GATEWAY),
    (MCPResponseTooLarge, status.HTTP_502_BAD_GATEWAY),
)

ERROR_RESPONSES = responses_for(STATUS_BY_ERROR, *IDENTITY_RESPONSES)


def get_read_workflow(request: Request) -> MCPReadWorkflow:
    return request.app.state.container.mcp_reads


def translate_read_error(error: MCPReadError) -> HTTPException:
    if isinstance(error, (MCPToolDenied, MCPInputRejected)):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(error, MCPProviderDisabled):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(
        error,
        (MCPAuditUnavailable, MCPBindingUnavailable, MCPGrantUnavailable),
    ):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, MCPRateLimited):
        # 429 rather than 502: the provider is answering correctly and the caller
        # should back off, which is a different instruction from "try again, the
        # network may be broken".
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(error, MCPCallTimeout):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    elif isinstance(
        error,
        (
            MCPProtocolRejected,
            MCPDNSRejected,
            MCPSchemaRejected,
            MCPTransportFailure,
            MCPRemoteToolFailure,
            MCPInvalidResponse,
            MCPResponseTooLarge,
        ),
    ):
        status_code = status.HTTP_502_BAD_GATEWAY
    else:  # pragma: no cover - defensive mapping for future safe errors
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.safe_message},
    )


@router.post("/reads", response_model=MCPReadBatchResult, responses=ERROR_RESPONSES)
async def execute_mcp_reads(
    batch: MCPReadBatch,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    workflow: Annotated[MCPReadWorkflow, Depends(get_read_workflow)],
) -> MCPReadBatchResult:
    try:
        return await workflow.execute_batch(batch, context)
    except MCPReadError as error:
        raise translate_read_error(error) from error
