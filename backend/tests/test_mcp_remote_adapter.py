import asyncio
import base64
from typing import Any

import httpx2
import pytest
from mcp_types import CallToolResult, ImageContent, ListToolsResult, TextContent, Tool

from app.core.identity import SecurityContext
from app.mcp.adapters.grants import BearerGrant
from app.mcp.adapters.remote import (
    ATLASSIAN_ENDPOINT,
    CALL_TIMEOUT_SECONDS,
    FIGMA_ENDPOINT,
    MAX_WIRE_RESPONSE_BYTES,
    SDKMCPReadSession,
    SDKRemoteMCPTransport,
    _LimitedAsyncByteStream,
    _reject_oversized_response,
)
from app.mcp.domain import MCPProvider
from app.mcp.errors import (
    MCPCallTimeout,
    MCPDNSRejected,
    MCPInvalidResponse,
    MCPProtocolRejected,
    MCPResponseTooLarge,
    MCPTransportFailure,
)


class StubGrantBroker:
    def __init__(self, token: str = "synthetic-adapter-token-0001") -> None:
        self.token = token
        self.calls: list[tuple[MCPProvider, SecurityContext]] = []

    async def acquire(
        self,
        *,
        provider: MCPProvider,
        context: SecurityContext,
    ) -> BearerGrant:
        self.calls.append((provider, context))
        return BearerGrant(
            provider=provider,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            access_token=self.token,
        )


class StubResolver:
    def __init__(
        self,
        addresses: tuple[str, ...] = ("8.8.8.8",),
        error: Exception | None = None,
    ) -> None:
        self.addresses = addresses
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, *, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        if self.error is not None:
            raise self.error
        return self.addresses


class StubSDKClient:
    def __init__(
        self,
        *,
        tool_result: CallToolResult | None = None,
        list_result: ListToolsResult | None = None,
    ) -> None:
        self.tool_result = tool_result or CallToolResult(
            content=[TextContent(text="safe")],
            structuredContent={"ok": True},
        )
        self.list_result = list_result or ListToolsResult(
            tools=[
                Tool(
                    name="whoami",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                )
            ]
        )
        self.list_calls = 0
        self.call_calls = 0

    async def list_tools(self, *, cursor: str | None = None) -> ListToolsResult:
        del cursor
        self.list_calls += 1
        return self.list_result

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        read_timeout_seconds: float,
    ) -> CallToolResult:
        del name, arguments
        assert read_timeout_seconds == CALL_TIMEOUT_SECONDS
        self.call_calls += 1
        return self.tool_result


def test_sdk_session_translates_only_text_and_image_content() -> None:
    output_schema = {
        "type": "object",
        "properties": {"safe": {"type": "boolean"}},
        "required": ["safe"],
        "additionalProperties": False,
    }
    client = StubSDKClient(
        tool_result=CallToolResult(
            content=[
                TextContent(text="safe text"),
                ImageContent(data="c2FmZQ==", mimeType="image/png"),
            ],
            structuredContent={"safe": True},
        ),
        list_result=ListToolsResult(
            tools=[
                Tool(
                    name="whoami",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    outputSchema=output_schema,
                )
            ]
        ),
    )
    session = SDKMCPReadSession(client=client, forbidden_secret="never-return-this-token")

    listed = asyncio.run(session.list_tools())
    result = asyncio.run(session.call_tool(tool_name="whoami", arguments={}))

    assert listed[0].name == "whoami"
    assert listed[0].input_schema["additionalProperties"] is False
    assert listed[0].output_schema == output_schema
    assert result.content[0].text == "safe text"
    assert result.content[1].data == "c2FmZQ=="
    assert result.content[1].mime_type == "image/png"
    assert result.structured_content == {"safe": True}


@pytest.mark.parametrize("secret_location", ["text", "structured"])
def test_sdk_session_blocks_echoed_bearer_secret(secret_location: str) -> None:
    secret = "synthetic-echoed-secret-0001"
    content = [TextContent(text=secret if secret_location == "text" else "safe")]
    structured = {"value": secret} if secret_location == "structured" else {"safe": True}
    client = StubSDKClient(
        tool_result=CallToolResult(content=content, structuredContent=structured)
    )
    session = SDKMCPReadSession(client=client, forbidden_secret=secret)

    with pytest.raises(MCPInvalidResponse) as caught:
        asyncio.run(session.call_tool(tool_name="whoami", arguments={}))

    assert secret not in str(caught.value)


def test_sdk_session_blocks_bearer_split_across_text_blocks() -> None:
    secret = "synthetic-split-secret-0001"
    client = StubSDKClient(
        tool_result=CallToolResult(
            content=[
                TextContent(text=secret[:12]),
                TextContent(text=secret[12:]),
            ]
        )
    )
    session = SDKMCPReadSession(client=client, forbidden_secret=secret)

    with pytest.raises(MCPInvalidResponse) as caught:
        asyncio.run(session.call_tool(tool_name="whoami", arguments={}))

    assert secret not in str(caught.value)
    assert client.call_calls == 1


def test_sdk_session_blocks_bearer_decoded_from_image_data() -> None:
    secret = "synthetic-image-secret-0001"
    encoded_secret = base64.b64encode(secret.encode("utf-8")).decode("ascii")
    client = StubSDKClient(
        tool_result=CallToolResult(
            content=[ImageContent(data=encoded_secret, mimeType="image/png")]
        )
    )
    session = SDKMCPReadSession(client=client, forbidden_secret=secret)

    with pytest.raises(MCPInvalidResponse) as caught:
        asyncio.run(session.call_tool(tool_name="whoami", arguments={}))

    assert secret not in str(caught.value)
    assert client.call_calls == 1


def test_sdk_session_blocks_bearer_split_between_content_and_structured_data() -> None:
    secret = "synthetic-combined-secret-0001"
    client = StubSDKClient(
        tool_result=CallToolResult(
            content=[TextContent(text=secret[:14])],
            structuredContent={"value": secret[14:]},
        )
    )
    session = SDKMCPReadSession(client=client, forbidden_secret=secret)

    with pytest.raises(MCPInvalidResponse) as caught:
        asyncio.run(session.call_tool(tool_name="whoami", arguments={}))

    assert secret not in str(caught.value)
    assert client.call_calls == 1


def test_sdk_session_does_not_retry_transport_failure() -> None:
    class FailingClient(StubSDKClient):
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            read_timeout_seconds: float,
        ) -> CallToolResult:
            del name, arguments, read_timeout_seconds
            self.call_calls += 1
            raise RuntimeError("provider detail must be expurgated")

    client = FailingClient()
    session = SDKMCPReadSession(client=client, forbidden_secret="synthetic-token")

    with pytest.raises(MCPTransportFailure, match="unavailable"):
        asyncio.run(session.call_tool(tool_name="whoami", arguments={}))

    assert client.call_calls == 1


def test_sdk_session_timeout_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.mcp.adapters.remote as remote

    class SlowClient(StubSDKClient):
        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            read_timeout_seconds: float,
        ) -> CallToolResult:
            del name, arguments, read_timeout_seconds
            self.call_calls += 1
            await asyncio.sleep(0.05)
            return self.tool_result

    monkeypatch.setattr(remote, "CALL_TIMEOUT_SECONDS", 0.001)
    client = SlowClient()
    session = SDKMCPReadSession(client=client, forbidden_secret="synthetic-token")

    with pytest.raises(MCPCallTimeout):
        asyncio.run(session.call_tool(tool_name="whoami", arguments={}))

    assert client.call_calls == 1


def test_wire_content_length_limit_is_checked_before_body_read() -> None:
    class Response:
        headers = {"content-length": str(MAX_WIRE_RESPONSE_BYTES + 1)}

    with pytest.raises(MCPResponseTooLarge):
        asyncio.run(_reject_oversized_response(Response()))  # type: ignore[arg-type]


def test_compressed_wire_response_is_refused_before_body_read() -> None:
    class Response:
        headers = {"content-encoding": "gzip"}

    with pytest.raises(MCPInvalidResponse):
        asyncio.run(_reject_oversized_response(Response()))  # type: ignore[arg-type]


def test_chunked_wire_response_is_bounded_without_content_length() -> None:
    class ChunkedStream(httpx2.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            yield b"12"
            yield b"34"

        async def aclose(self) -> None:
            return None

    response = httpx2.Response(200, stream=ChunkedStream())

    async def consume_response() -> None:
        await _reject_oversized_response(response)
        assert isinstance(response.stream, _LimitedAsyncByteStream)
        response.stream._maximum_bytes = 3
        async for _ in response.stream:
            pass

    with pytest.raises(MCPResponseTooLarge):
        asyncio.run(consume_response())


def test_remote_transport_uses_fixed_endpoint_no_redirects_and_bounded_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.mcp.adapters.remote as remote

    captured: dict[str, Any] = {}

    class FakeHTTPClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["http_kwargs"] = kwargs

        async def __aenter__(self) -> "FakeHTTPClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeClient:
        protocol_version = "2026-07-28"

        def __init__(self, transport: object, **kwargs: Any) -> None:
            captured["client_transport"] = transport
            captured["client_kwargs"] = kwargs

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    def fake_streamable_http_client(
        endpoint: str,
        *,
        http_client: object,
        terminate_on_close: bool,
    ) -> object:
        captured["endpoint"] = endpoint
        captured["transport_http_client"] = http_client
        captured["terminate_on_close"] = terminate_on_close
        return object()

    monkeypatch.setattr(remote.httpx2, "AsyncClient", FakeHTTPClient)
    monkeypatch.setattr(remote, "Client", FakeClient)
    monkeypatch.setattr(remote, "streamable_http_client", fake_streamable_http_client)
    broker = StubGrantBroker()
    resolver = StubResolver()
    transport = SDKRemoteMCPTransport(grant_broker=broker, resolver=resolver)
    context = SecurityContext(tenant_id="tenant-a", user_id="user-a")

    async def connect_once() -> str:
        async with transport.connect(provider=MCPProvider.FIGMA, context=context) as session:
            return session.protocol_version

    assert asyncio.run(connect_once()) == "2026-07-28"
    assert captured["endpoint"] == FIGMA_ENDPOINT
    assert captured["terminate_on_close"] is False
    http_kwargs = captured["http_kwargs"]
    assert http_kwargs["follow_redirects"] is False
    assert http_kwargs["trust_env"] is False
    assert http_kwargs["headers"] == {
        "Accept-Encoding": "identity",
        "Authorization": f"Bearer {broker.token}",
    }
    assert http_kwargs["timeout"].connect == 3.0
    assert http_kwargs["timeout"].read == 30.0
    assert captured["client_kwargs"]["cache"] is None
    assert captured["client_kwargs"]["mode"] == "auto"
    assert resolver.calls == [("mcp.figma.com", 443)]


@pytest.mark.parametrize("protocol_version", ["2025-06-18", "2025-03-26", "2024-11-05"])
def test_remote_transport_rejects_unapproved_negotiated_protocol(
    monkeypatch: pytest.MonkeyPatch,
    protocol_version: str,
) -> None:
    import app.mcp.adapters.remote as remote

    class FakeHTTPClient:
        def __init__(self, **_: Any) -> None: ...

        async def __aenter__(self) -> "FakeHTTPClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeClient:
        def __init__(self, *_: object, **__: Any) -> None:
            self.protocol_version = protocol_version

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(remote.httpx2, "AsyncClient", FakeHTTPClient)
    monkeypatch.setattr(remote, "Client", FakeClient)
    monkeypatch.setattr(remote, "streamable_http_client", lambda *_args, **_kwargs: object())
    transport = SDKRemoteMCPTransport(
        grant_broker=StubGrantBroker(),
        resolver=StubResolver(),
    )

    async def connect_once() -> None:
        async with transport.connect(
            provider=MCPProvider.ATLASSIAN,
            context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
        ):
            raise AssertionError("An unapproved protocol must not yield a session")

    with pytest.raises(MCPProtocolRejected):
        asyncio.run(connect_once())

    assert ATLASSIAN_ENDPOINT == "https://mcp.atlassian.com/v1/mcp"


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("169.254.169.254",),
        ("10.0.0.1",),
        ("8.8.8.8", "192.168.1.10"),
        ("::1",),
    ],
)
def test_dns_preflight_refuses_private_metadata_and_mixed_answers_before_grant(
    addresses: tuple[str, ...],
) -> None:
    broker = StubGrantBroker()
    transport = SDKRemoteMCPTransport(
        grant_broker=broker,
        resolver=StubResolver(addresses),
    )

    async def connect_once() -> None:
        async with transport.connect(
            provider=MCPProvider.FIGMA,
            context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
        ):
            raise AssertionError("A rejected DNS answer must not open a transport")

    with pytest.raises(MCPDNSRejected):
        asyncio.run(connect_once())

    assert broker.calls == []


def test_dns_preflight_resolution_failure_is_safe_and_precedes_grant() -> None:
    broker = StubGrantBroker()
    transport = SDKRemoteMCPTransport(
        grant_broker=broker,
        resolver=StubResolver(error=OSError("synthetic resolver detail")),
    )

    async def connect_once() -> None:
        async with transport.connect(
            provider=MCPProvider.ATLASSIAN,
            context=SecurityContext(tenant_id="tenant-a", user_id="user-a"),
        ):
            raise AssertionError("A resolver failure must not open a transport")

    with pytest.raises(MCPDNSRejected, match="not approved"):
        asyncio.run(connect_once())

    assert broker.calls == []
