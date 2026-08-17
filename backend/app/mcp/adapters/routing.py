"""Selects the transport that serves a provider.

Providers are not reached the same way: Atlassian speaks MCP over Streamable HTTP,
Figma is read through its REST API because its MCP server admits only catalogue
clients. The read workflow should not know that, so the choice is made here and the
workflow keeps one transport-shaped dependency.

The table is closed on purpose. An unrouted provider fails the read rather than
falling back to a default transport, because a silent fallback would send one
provider's credential to another provider's endpoint.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from app.core.identity import SecurityContext
from app.mcp.domain import MCPBindingKind, MCPProvider
from app.mcp.errors import MCPTransportFailure
from app.mcp.ports import MCPReadSession, MCPReadTransport


class ProviderRoutedTransport:
    def __init__(self, routes: Mapping[MCPProvider, MCPReadTransport]) -> None:
        self._routes = dict(routes)

    @asynccontextmanager
    async def connect(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> AsyncIterator[MCPReadSession]:
        transport = self._routes.get(provider)
        if transport is None:
            raise MCPTransportFailure()
        async with transport.connect(
            provider=provider, binding=binding, context=context
        ) as session:
            yield session
