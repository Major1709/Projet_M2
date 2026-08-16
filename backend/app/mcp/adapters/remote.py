import base64
import binascii
import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import ImageContent, TextContent

from app.core.identity import SecurityContext
from app.mcp.adapters.grants import DelegatedGrantBroker
from app.mcp.adapters.http_guard import (
    CALL_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    HTTPS_PORT,
    EndpointResolver,
    PinnedAddressTransport,
    SystemEndpointResolver,
    is_approved_public_address,
    reject_oversized_response,
    validate_fixed_endpoint,
)
from app.mcp.domain import MCPBindingKind, MCPProvider
from app.mcp.errors import (
    MCPCallTimeout,
    MCPDNSRejected,
    MCPInvalidResponse,
    MCPProtocolRejected,
    MCPReadError,
    MCPRemoteToolFailure,
    MCPTransportFailure,
)
from app.mcp.ports import (
    MCPReadSession,
    RemoteContentBlock,
    RemoteToolDescription,
    RemoteToolResult,
)
from app.mcp.registry import (
    APPROVED_REMOTE_PROTOCOL_VERSIONS,
    ATLASSIAN_ENDPOINT,
)

MAX_LISTED_TOOLS = 256
MAX_TOOL_LIST_PAGES = 10

_ENDPOINTS = {
    MCPProvider.ATLASSIAN: ATLASSIAN_ENDPOINT,
}


for _endpoint in _ENDPOINTS.values():
    validate_fixed_endpoint(_endpoint)


def _contains_across_text_fragments(secret: str, fragments: Iterable[str]) -> bool:
    if not secret:
        return True
    overlap_length = len(secret) - 1
    overlap = ""
    for fragment in fragments:
        candidate = overlap + fragment
        if secret in candidate:
            return True
        overlap = candidate[-overlap_length:] if overlap_length else ""
    return False


def _contains_across_byte_fragments(secret: bytes, fragments: Iterable[bytes]) -> bool:
    if not secret:
        return True
    overlap_length = len(secret) - 1
    overlap = b""
    for fragment in fragments:
        candidate = overlap + fragment
        if secret in candidate:
            return True
        overlap = candidate[-overlap_length:] if overlap_length else b""
    return False


def _structured_text_fragments(value: Any, seen: set[int] | None = None) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (dict, list, tuple)):
        return []

    seen = set() if seen is None else seen
    identity = id(value)
    if identity in seen:
        return []
    seen.add(identity)
    fragments: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            fragments.extend(_structured_text_fragments(child, seen))
    else:
        for child in value:
            fragments.extend(_structured_text_fragments(child, seen))
    return fragments


class SDKMCPReadSession:
    def __init__(self, *, client: Client, forbidden_secret: str) -> None:
        self._client = client
        self._forbidden_secret = forbidden_secret

    @property
    def protocol_version(self) -> str:
        version = self._client.protocol_version
        if version is None:  # pragma: no cover - an entered client always has a version
            raise MCPProtocolRejected()
        return version

    async def list_tools(self) -> tuple[RemoteToolDescription, ...]:
        tools: list[RemoteToolDescription] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        try:
            with anyio.fail_after(CALL_TIMEOUT_SECONDS):
                for _ in range(MAX_TOOL_LIST_PAGES):
                    result = await self._client.list_tools(cursor=cursor)
                    for tool in result.tools:
                        tools.append(
                            RemoteToolDescription(
                                name=tool.name,
                                input_schema=tool.input_schema,
                                output_schema=tool.output_schema,
                            )
                        )
                    if len(tools) > MAX_LISTED_TOOLS:
                        raise MCPInvalidResponse()
                    cursor = result.next_cursor
                    if cursor is None:
                        return tuple(tools)
                    if cursor in seen_cursors:
                        raise MCPInvalidResponse()
                    seen_cursors.add(cursor)
        except BaseException as error:
            mapped = _map_transport_exception(error)
            if mapped is error:
                raise
            raise mapped from error
        raise MCPInvalidResponse()

    async def call_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> RemoteToolResult:
        try:
            with anyio.fail_after(CALL_TIMEOUT_SECONDS):
                result = await self._client.call_tool(
                    tool_name,
                    arguments,
                    read_timeout_seconds=CALL_TIMEOUT_SECONDS,
                )
        except BaseException as error:
            mapped = _map_transport_exception(error)
            if mapped is error:
                raise
            raise mapped from error

        if result.is_error:
            raise MCPRemoteToolFailure()
        if result.result_type != "complete":
            raise MCPInvalidResponse()
        if self._contains_forbidden_secret(result.content, result.structured_content):
            raise MCPInvalidResponse()

        blocks: list[RemoteContentBlock] = []
        for block in result.content:
            if isinstance(block, TextContent):
                blocks.append(RemoteContentBlock(kind="text", text=block.text))
            elif isinstance(block, ImageContent):
                blocks.append(
                    RemoteContentBlock(
                        kind="image",
                        data=block.data,
                        mime_type=block.mime_type,
                    )
                )
            else:
                # Resource links, embedded resources and audio are deliberately not followed.
                blocks.append(RemoteContentBlock(kind="unsupported"))
        return RemoteToolResult(
            content=tuple(blocks),
            structured_content=result.structured_content,
        )

    def _contains_forbidden_secret(self, content: list[Any], structured: Any) -> bool:
        text_fragments: list[str] = []
        raw_content_fragments: list[str] = []
        decoded_content_fragments: list[bytes] = []
        for block in content:
            if isinstance(block, TextContent):
                text_fragments.append(block.text)
                raw_content_fragments.append(block.text)
                decoded_content_fragments.append(block.text.encode("utf-8"))
            elif isinstance(block, ImageContent):
                raw_content_fragments.append(block.data)
                try:
                    decoded_content_fragments.append(
                        base64.b64decode(block.data, validate=True)
                    )
                except (binascii.Error, ValueError):
                    # Invalid image data is rejected later by result normalization.
                    decoded_content_fragments.append(b"")

        structured_fragments = _structured_text_fragments(structured)
        combined_text_fragments = (*text_fragments, *structured_fragments)
        if _contains_across_text_fragments(
            self._forbidden_secret,
            combined_text_fragments,
        ):
            return True
        if _contains_across_text_fragments(
            self._forbidden_secret,
            (*raw_content_fragments, *structured_fragments),
        ):
            return True
        if _contains_across_byte_fragments(
            self._forbidden_secret.encode("utf-8"),
            (
                *decoded_content_fragments,
                *(fragment.encode("utf-8") for fragment in structured_fragments),
            ),
        ):
            return True

        try:
            serialized = json.dumps(structured, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            return False
        return self._forbidden_secret in serialized


def _iter_leaf_exceptions(error: BaseException) -> Iterable[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        for child in error.exceptions:
            yield from _iter_leaf_exceptions(child)
    else:
        yield error


def _map_transport_exception(error: BaseException) -> BaseException:
    """Map an SDK failure onto the MCP error taxonomy, flattening exception groups.

    The SDK client runs its session on an internal task group, so any failure can
    reach us wrapped in a ``BaseExceptionGroup``. Cancellation is returned intact
    so the surrounding cancel scopes keep their own unwinding semantics.
    """
    leaves = tuple(_iter_leaf_exceptions(error))
    cancelled_exc = anyio.get_cancelled_exc_class()
    if any(
        isinstance(leaf, cancelled_exc | GeneratorExit | KeyboardInterrupt | SystemExit)
        for leaf in leaves
    ):
        return error
    for leaf in leaves:
        if isinstance(leaf, MCPReadError):
            return leaf
    if any(isinstance(leaf, TimeoutError) for leaf in leaves):
        return MCPCallTimeout()
    return MCPTransportFailure()


class SDKRemoteMCPTransport:
    """MCP Python SDK v2 Streamable HTTP adapter with no retries or redirects."""

    def __init__(
        self,
        *,
        grant_broker: DelegatedGrantBroker,
        resolver: EndpointResolver | None = None,
    ) -> None:
        self._grant_broker = grant_broker
        self._resolver = resolver or SystemEndpointResolver()

    @asynccontextmanager
    async def connect(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> AsyncIterator[MCPReadSession]:
        endpoint = _ENDPOINTS.get(provider)
        if endpoint is None:
            raise MCPTransportFailure()
        parsed_endpoint = urlsplit(endpoint)
        hostname = parsed_endpoint.hostname
        if hostname is None:  # pragma: no cover - fixed endpoints are checked at import
            raise MCPDNSRejected()
        try:
            addresses = await self._resolver.resolve(hostname=hostname, port=HTTPS_PORT)
        except Exception as error:
            raise MCPDNSRejected() from error
        if not addresses or any(
            not is_approved_public_address(address) for address in addresses
        ):
            raise MCPDNSRejected()
        # Every answer had to be approved; this is the one actually contacted, so
        # the connection cannot land on a later resolution nobody validated.
        pinned_address = addresses[0]
        grant = await self._grant_broker.acquire(
            provider=provider, binding=binding, context=context
        )
        timeout = httpx2.Timeout(
            CALL_TIMEOUT_SECONDS,
            connect=CONNECT_TIMEOUT_SECONDS,
            read=CALL_TIMEOUT_SECONDS,
            write=CALL_TIMEOUT_SECONDS,
            pool=CONNECT_TIMEOUT_SECONDS,
        )
        http_client = httpx2.AsyncClient(
            headers={
                "Accept-Encoding": "identity",
                "Authorization": f"Bearer {grant.access_token}",
            },
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"response": [reject_oversized_response]},
            transport=PinnedAddressTransport(hostname=hostname, address=pinned_address),
        )
        transport = streamable_http_client(
            endpoint,
            http_client=http_client,
            terminate_on_close=False,
        )
        client = Client(
            transport,
            read_timeout_seconds=CALL_TIMEOUT_SECONDS,
            mode="auto",
            cache=None,
            input_required_max_rounds=0,
        )
        try:
            async with http_client, client:
                if client.protocol_version not in APPROVED_REMOTE_PROTOCOL_VERSIONS:
                    raise MCPProtocolRejected()
                yield SDKMCPReadSession(
                    client=client,
                    forbidden_secret=grant.access_token,
                )
        except BaseException as error:
            mapped = _map_transport_exception(error)
            if mapped is error:
                raise
            raise mapped from error
