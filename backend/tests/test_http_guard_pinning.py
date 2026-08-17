import anyio
import httpx2
import pytest

from app.mcp.adapters.http_guard import PinnedAddressTransport


def sent_through(hostname: str, address: str, url: str) -> httpx2.Request:
    """Drive one request through the pinned transport and capture what it sent."""

    seen: list[httpx2.Request] = []

    async def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={})

    transport = PinnedAddressTransport(
        hostname=hostname,
        address=address,
        inner=httpx2.MockTransport(record),
    )

    async def call() -> None:
        async with httpx2.AsyncClient(transport=transport) as client:
            await client.get(url)

    anyio.run(call)
    return seen[0]


def test_the_connection_goes_to_the_approved_address() -> None:
    # Validating a resolution and then connecting by hostname leaves the client to
    # resolve a second time, and it is that second answer which is contacted.
    request = sent_through("api.groq.com", "203.0.113.7", "https://api.groq.com/openai/v1/models")

    assert request.url.host == "203.0.113.7"


def test_the_destination_keeps_its_identity() -> None:
    # Host for the server's routing, SNI for the handshake -- and because
    # certificate verification runs against the SNI name, pinning the address must
    # not become a way to accept a certificate that was never valid for it.
    request = sent_through("api.figma.com", "203.0.113.9", "https://api.figma.com/v1/files/ABC")

    assert request.headers["Host"] == "api.figma.com"
    assert request.extensions["sni_hostname"] == "api.figma.com"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.groq.com/openai/v1/chat/completions?stream=false",
        "https://api.figma.com/v1/files/ABC/nodes",
    ],
)
def test_only_the_host_is_rewritten(url: str) -> None:
    # Otherwise a guard meant to fix the destination could quietly move the request
    # to a different resource.
    original = httpx2.URL(url)

    request = sent_through(original.host, "203.0.113.1", url)

    assert request.url.scheme == original.scheme
    assert request.url.path == original.path
    assert request.url.query == original.query
    assert request.url.port == original.port


def test_an_ipv6_address_is_pinned_too() -> None:
    request = sent_through("api.groq.com", "2001:db8::1", "https://api.groq.com/openai/v1/models")

    assert request.url.host == "2001:db8::1"
    assert request.headers["Host"] == "api.groq.com"
