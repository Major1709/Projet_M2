from typing import Protocol

from app.core.identity import SecurityContext
from app.mcp.domain import (
    MCPExecutionResult,
    MCPToolCall,
    PermissionCheck,
    PermissionDecision,
)


class SourcePermissionVerifier(Protocol):
    """Reauthorizes a precise source action under the current user identity."""

    def check(self, request: PermissionCheck) -> PermissionDecision: ...


class MCPToolGateway(Protocol):
    """Transport boundary. Never expose this object or source credentials to the LLM."""

    def execute_read(
        self,
        *,
        call: MCPToolCall,
        context: SecurityContext,
    ) -> MCPExecutionResult: ...

    def execute_mutation(
        self,
        *,
        call: MCPToolCall,
        context: SecurityContext,
        idempotency_key: str,
    ) -> MCPExecutionResult: ...
