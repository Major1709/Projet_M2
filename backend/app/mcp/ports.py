from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.identity import SecurityContext
from app.mcp.domain import (
    MCPBindingKind,
    MCPExecutionResult,
    MCPProvider,
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


@dataclass(frozen=True)
class RemoteToolDescription:
    name: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class RemoteContentBlock:
    kind: str
    text: str | None = None
    data: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class RemoteToolResult:
    content: tuple[RemoteContentBlock, ...]
    structured_content: Any = None


class MCPReadSession(Protocol):
    @property
    def protocol_version(self) -> str: ...

    async def list_tools(self) -> tuple[RemoteToolDescription, ...]: ...

    async def call_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> RemoteToolResult: ...


class MCPReadTransport(Protocol):
    """Async read-only boundary; credentials and SDK objects remain in its adapter."""

    def connect(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> AbstractAsyncContextManager[MCPReadSession]: ...
