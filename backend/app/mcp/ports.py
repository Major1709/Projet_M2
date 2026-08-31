from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

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
class MutationReservation:
    """The single idempotency key an approved proposal may ever be executed under."""

    idempotency_key: str
    # Set once a terminal outcome was recorded. A retry then replays that outcome
    # instead of calling the provider again.
    completed: bool = False
    result: MCPExecutionResult | None = None


class MutationIdempotencyStore(Protocol):
    """Mints and holds the idempotency key of a mutation, durably and server-side.

    The key is never accepted from a caller. A client-chosen key lets two different
    approved actions collide under one key -- the provider then silently discards the
    second -- or lets one action be replayed under a fresh key, which defeats the
    provider's own deduplication.

    ``reserve`` is idempotent by construction: the first call mints a key and commits
    it, every later call for the same proposal returns that same key. It must be
    durable before the provider is contacted, because a reservation lost to a crash
    would be reminted and the provider would see a second, distinct request for an
    action the human approved once.
    """

    def find(self, *, tenant_id: str, proposal_id: UUID) -> MutationReservation | None:
        """Read an existing reservation without creating one.

        Separate from ``reserve`` on purpose: replaying a finished mutation has to be
        answered before the proposal's state is examined, since that state is by then
        COMPLETED rather than APPROVED. Minting a key at that point would hand one to
        a proposal that was never approved.
        """
        ...

    def reserve(self, *, tenant_id: str, proposal_id: UUID) -> MutationReservation: ...

    def record_outcome(
        self,
        *,
        tenant_id: str,
        proposal_id: UUID,
        result: MCPExecutionResult,
    ) -> None: ...


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
