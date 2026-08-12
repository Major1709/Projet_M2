import base64
import binascii
import ipaddress
import json
import socket
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any, Protocol
from urllib.parse import urlsplit

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import ImageContent, TextContent

from app.core.identity import SecurityContext
from app.mcp.adapters.grants import DelegatedGrantBroker
from app.mcp.domain import MCPProvider
from app.mcp.errors import (
    MCPCallTimeout,
    MCPDNSRejected,
    MCPInvalidResponse,
    MCPProtocolRejected,
    MCPReadError,
    MCPRemoteToolFailure,
    MCPResponseTooLarge,
    MCPTransportFailure,
)
from app.mcp.ports import (
    MCPReadSession,
    RemoteContentBlock,
    RemoteToolDescription,
    RemoteToolResult,
)
from app.mcp.registry import (
    APPROVED_PROTOCOL_VERSIONS,
    ATLASSIAN_ENDPOINT,
    FIGMA_ENDPOINT,
)

CONNECT_TIMEOUT_SECONDS = 3.0
CALL_TIMEOUT_SECONDS = 30.0
MAX_LISTED_TOOLS = 256
MAX_TOOL_LIST_PAGES = 10
MAX_WIRE_RESPONSE_BYTES = 12 * 1024 * 1024

_ENDPOINTS = {
    MCPProvider.ATLASSIAN: ATLASSIAN_ENDPOINT,
    MCPProvider.FIGMA: FIGMA_ENDPOINT,
}


def _validate_fixed_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MCP endpoints must be fixed HTTPS destinations")


for _endpoint in _ENDPOINTS.values():
    _validate_fixed_endpoint(_endpoint)


class _LimitedAsyncByteStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream, maximum_bytes: int) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes

    async def __aiter__(self) -> AsyncIterator[bytes]:
        seen = 0
        async for chunk in self._stream:
            seen += len(chunk)
            if seen > self._maximum_bytes:
                raise MCPResponseTooLarge()
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


async def _reject_oversized_response(response: httpx2.Response) -> None:
    content_encoding = response.headers.get("content-encoding", "").strip().lower()
    if content_encoding not in {"", "identity"}:
        raise MCPInvalidResponse()
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise MCPInvalidResponse() from error
        if declared_size < 0:
            raise MCPInvalidResponse()
        if declared_size > MAX_WIRE_RESPONSE_BYTES:
            raise MCPResponseTooLarge()
    if not isinstance(response.stream, httpx2.AsyncByteStream):
        raise MCPInvalidResponse()
    response.stream = _LimitedAsyncByteStream(response.stream, MAX_WIRE_RESPONSE_BYTES)


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


class EndpointResolver(Protocol):
    async def resolve(self, *, hostname: str, port: int) -> tuple[str, ...]: ...


class SystemEndpointResolver:
    async def resolve(self, *, hostname: str, port: int) -> tuple[str, ...]:
        def resolve_blocking() -> tuple[str, ...]:
            records = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            return tuple(record[4][0] for record in records)

        return await anyio.to_thread.run_sync(resolve_blocking)


def _is_approved_public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_global


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
        except TimeoutError as error:
            raise MCPCallTimeout() from error
        except MCPReadError:
            raise
        except Exception as error:
            raise MCPTransportFailure() from error
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
        except TimeoutError as error:
            raise MCPCallTimeout() from error
        except MCPReadError:
            raise
        except Exception as error:
            raise MCPTransportFailure() from error

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
            addresses = await self._resolver.resolve(hostname=hostname, port=443)
        except Exception as error:
            raise MCPDNSRejected() from error
        if not addresses or any(
            not _is_approved_public_address(address) for address in addresses
        ):
            raise MCPDNSRejected()
        grant = await self._grant_broker.acquire(provider=provider, context=context)
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
            event_hooks={"response": [_reject_oversized_response]},
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
        entered = False
        try:
            async with http_client:
                try:
                    with anyio.fail_after(CALL_TIMEOUT_SECONDS):
                        await client.__aenter__()
                        entered = True
                    if client.protocol_version not in APPROVED_PROTOCOL_VERSIONS:
                        raise MCPProtocolRejected()
                    yield SDKMCPReadSession(
                        client=client,
                        forbidden_secret=grant.access_token,
                    )
                finally:
                    if entered:
                        with anyio.move_on_after(CONNECT_TIMEOUT_SECONDS):
                            await client.__aexit__(None, None, None)
        except TimeoutError as error:
            raise MCPCallTimeout() from error
        except MCPReadError:
            raise
        except Exception as error:
            raise MCPTransportFailure() from error
