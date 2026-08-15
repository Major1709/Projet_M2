"""Transport-level guards shared by every outbound MCP adapter.

These controls belong to the act of leaving the process, not to any one protocol,
so they live apart from the MCP SDK adapter that first carried them. Both the
remote MCP transport and the Figma REST transport enforce the same rules: a fixed
HTTPS destination, an address that is publicly routable, and a response whose size
is bounded before it is read into memory.

Keeping one copy matters more than the small indirection it costs. Two adapters
each holding their own address check is two places to weaken, and the second one
is the one nobody re-reads.
"""

import ipaddress
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol
from urllib.parse import urlsplit

import anyio
import httpx2

from app.mcp.errors import MCPInvalidResponse, MCPResponseTooLarge

CONNECT_TIMEOUT_SECONDS = 3.0
CALL_TIMEOUT_SECONDS = 30.0
MAX_WIRE_RESPONSE_BYTES = 12 * 1024 * 1024
# Every outbound destination is contacted on the standard HTTPS port. Fixing it
# here rather than reading it from the URL removes a lever: a destination that
# could name its own port could reach services that only listen off 443.
HTTPS_PORT = 443


def validate_fixed_endpoint(endpoint: str) -> None:
    """Reject anything that is not a bare, fixed HTTPS destination.

    Called at module import by each adapter over its own endpoint table, so a
    malformed destination fails the process at start-up rather than at the first
    read. Credentials in the authority, a query, or a fragment are refused because
    a fixed endpoint has no use for them and each one is a place to hide a
    redirection.
    """

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.port not in {None, HTTPS_PORT}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MCP endpoints must be fixed HTTPS destinations")


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


def is_approved_public_address(address: str) -> bool:
    """True only for a publicly routable address.

    ``is_global`` rejects loopback, private ranges, link-local -- and with it the
    cloud metadata endpoint, which is the usual prize of a server-side request
    forgery. IPv4-mapped IPv6 is unwrapped first, otherwise ``::ffff:127.0.0.1``
    would pass as a global IPv6 address.
    """

    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_global


class LimitedAsyncByteStream(httpx2.AsyncByteStream):
    """Stops a response body at a byte ceiling as it streams, before it is buffered."""

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


async def bound_response(response: httpx2.Response, maximum_bytes: int) -> None:
    """Bound a response before it is read, whatever its declared length claims.

    A declared ``content-length`` is only a claim, so it is checked and then the
    stream is wrapped anyway: a server that understates its length is caught by the
    wrapper. Content encodings other than identity are refused outright, because a
    compressed body's decoded size is unbounded by anything we can see here.
    """

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
        if declared_size > maximum_bytes:
            raise MCPResponseTooLarge()
    if not isinstance(response.stream, httpx2.AsyncByteStream):
        raise MCPInvalidResponse()
    response.stream = LimitedAsyncByteStream(response.stream, maximum_bytes)


def bounded_response_hook(maximum_bytes: int) -> Callable[[httpx2.Response], Awaitable[None]]:
    """Build an httpx response hook that enforces a caller-chosen byte ceiling.

    The MCP transports read whole documents and share one generous ceiling; a chat
    completion is orders of magnitude smaller and deserves its own. Passing the
    ceiling in rather than reading a module constant keeps a single implementation
    of the check while letting each caller bound its own blast radius.
    """

    if maximum_bytes <= 0:
        raise ValueError("A response ceiling must be a positive number of bytes")

    async def hook(response: httpx2.Response) -> None:
        await bound_response(response, maximum_bytes)

    return hook


async def reject_oversized_response(response: httpx2.Response) -> None:
    """Bound a response at the shared MCP wire ceiling."""

    await bound_response(response, MAX_WIRE_RESPONSE_BYTES)
