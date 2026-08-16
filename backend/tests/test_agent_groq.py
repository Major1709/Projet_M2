import gzip
import json
import logging
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.agent.adapters.groq import (
    GROQ_ENDPOINT,
    MAX_API_KEY_BYTES,
    MAX_COMPLETION_TOKENS,
    MAX_RESPONSE_BYTES,
    MAX_TEXT_CHARACTERS,
    MAX_TOOL_ARGUMENTS_CHARACTERS,
    MAX_TOOL_CALL_ID_CHARACTERS,
    MAX_TOOL_CALLS,
    MAX_TOOL_NAME_CHARACTERS,
    GroqLLMProvider,
)
from app.agent.domain import LLMRequest
from app.agent.errors import (
    LLMCallTimeout,
    LLMCredentialUnavailable,
    LLMDNSRejected,
    LLMInvalidResponse,
    LLMProviderRefused,
    LLMRateLimited,
    LLMRequestTooLarge,
    LLMResponseTooLarge,
    LLMTransportFailure,
)
from app.core.config import Settings
from app.core.identity import SecurityContext
from app.mcp.domain import ToolActionClass

CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")
REQUEST = LLMRequest(
    messages=({"role": "user", "content": "Quels tickets sont ouverts ?"},),
    correlation_id="corr-1",
)


class FakeResolver:
    """Resolves to whatever the test wants, without touching the network."""

    def __init__(self, addresses: tuple[str, ...] = ("93.184.216.34",)) -> None:
        self.addresses = addresses
        self.calls = 0

    async def resolve(self, *, hostname: str, port: int) -> tuple[str, ...]:
        self.calls += 1
        self.hostname = hostname
        self.port = port
        return self.addresses


def api_key_file(tmp_path: Path, value: bytes = b"gsk_" + b"a" * 40 + b"\n") -> Path:
    path = tmp_path / "groq_api_key"
    path.write_bytes(value)
    return path


def completion(
    *,
    text: str = "Deux tickets sont ouverts.",
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "model": "qwen/qwen3.6-27b",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
    }


def provider_for(
    tmp_path: Path,
    handler,
    *,
    model: str = "qwen/qwen3.6-27b",
    max_completion_tokens: int = MAX_COMPLETION_TOKENS,
    resolver: FakeResolver | None = None,
    key: bytes | None = None,
) -> GroqLLMProvider:
    return GroqLLMProvider(
        api_key_file=api_key_file(tmp_path) if key is None else api_key_file(tmp_path, key),
        model=model,
        max_completion_tokens=max_completion_tokens,
        resolver=resolver or FakeResolver(),
        transport=httpx2.MockTransport(handler),
    )


def json_handler(document: Any, *, status_code: int = 200, headers: dict[str, str] | None = None):
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx2.Response(
            status_code,
            content=json.dumps(document).encode("utf-8"),
            headers={"content-type": "application/json", **(headers or {})},
        )

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


def test_the_endpoint_is_pinned_and_not_configurable() -> None:
    assert GROQ_ENDPOINT == "https://api.groq.com/openai/v1"
    # A destination that configuration can move is a destination that can be pointed
    # at a server we never approved -- carrying the API key with it on the first call.
    #
    # Asserted as a property rather than a list of guessed names: enumerating
    # forbidden names only catches the spellings someone thought of, and a field
    # called llm_groq_url would reintroduce the lever without failing the test.
    destination_words = ("url", "endpoint", "host", "base", "origin", "address")
    offending = [
        name
        for name in Settings.model_fields
        if ("groq" in name or "llm" in name) and any(word in name for word in destination_words)
    ]
    assert offending == []
    assert Settings.model_fields["llm_groq_max_completion_tokens"].default == MAX_COMPLETION_TOKENS


@pytest.mark.anyio
async def test_the_request_carries_the_model_messages_and_bounded_completion(
    tmp_path: Path,
) -> None:
    handler = json_handler(completion())
    provider = provider_for(tmp_path, handler)

    await provider.generate(request=REQUEST, context=CONTEXT)

    payload = handler.seen["payload"]
    assert handler.seen["url"] == f"{GROQ_ENDPOINT}/chat/completions"
    assert payload["model"] == "qwen/qwen3.6-27b"
    assert payload["messages"] == [{"role": "user", "content": "Quels tickets sont ouverts ?"}]
    # The caller's own budget, not the model's maximum: a provider charges the whole
    # requested budget against the credential's allowance whether it is used or not.
    assert payload["max_tokens"] == REQUEST.max_completion_tokens == 2_048
    # Nothing is offered that the caller did not declare.
    assert "tools" not in payload


@pytest.mark.anyio
async def test_a_caller_cannot_raise_the_completion_ceiling(tmp_path: Path) -> None:
    handler = json_handler(completion())
    provider = provider_for(tmp_path, handler, max_completion_tokens=1_000_000)

    await provider.generate(
        request=REQUEST.model_copy(update={"max_completion_tokens": MAX_COMPLETION_TOKENS}),
        context=CONTEXT,
    )

    assert handler.seen["payload"]["max_tokens"] == MAX_COMPLETION_TOKENS


@pytest.mark.anyio
async def test_the_adapter_ceiling_caps_a_larger_caller_ask(tmp_path: Path) -> None:
    handler = json_handler(completion())
    provider = provider_for(tmp_path, handler, max_completion_tokens=512)

    await provider.generate(
        request=REQUEST.model_copy(update={"max_completion_tokens": 8_192}),
        context=CONTEXT,
    )

    assert handler.seen["payload"]["max_tokens"] == 512


@pytest.mark.anyio
async def test_declared_tools_are_forwarded_verbatim(tmp_path: Path) -> None:
    schema = {
        "type": "function",
        "function": {
            "name": "getJiraIssue",
            "parameters": {"type": "object", "properties": {"issueIdOrKey": {"type": "string"}}},
        },
    }
    handler = json_handler(completion())
    provider = provider_for(tmp_path, handler)

    await provider.generate(
        request=REQUEST.model_copy(update={"tools": (schema,)}),
        context=CONTEXT,
    )

    assert handler.seen["payload"]["tools"] == [schema]


@pytest.mark.anyio
async def test_the_key_is_sent_as_a_bearer_and_encoding_stays_identity(tmp_path: Path) -> None:
    handler = json_handler(completion())
    provider = provider_for(tmp_path, handler, key=b"gsk_" + b"b" * 40 + b"\n")

    await provider.generate(request=REQUEST, context=CONTEXT)

    headers = handler.seen["headers"]
    assert headers["authorization"] == "Bearer gsk_" + "b" * 40
    # A compressed body's decoded size is unbounded by anything measurable on the
    # wire, which would make the byte ceiling below meaningless.
    assert headers["accept-encoding"] == "identity"


@pytest.mark.anyio
async def test_the_address_is_checked_before_the_key_is_read(tmp_path: Path) -> None:
    resolver = FakeResolver(addresses=("127.0.0.1",))
    provider = GroqLLMProvider(
        api_key_file=tmp_path / "absent",
        model="qwen/qwen3.6-27b",
        resolver=resolver,
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, json=completion())),
    )

    # A missing key file would raise its own error. Getting the DNS refusal proves the
    # address check runs first, so a hijacked resolver never reaches a process that is
    # holding the credential in memory.
    with pytest.raises(LLMDNSRejected):
        await provider.generate(request=REQUEST, context=CONTEXT)
    assert resolver.calls == 1
    assert resolver.hostname == "api.groq.com"
    assert resolver.port == 443


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("key_bytes", "reason"),
    [
        (b"short\n", "too few bytes"),
        (b"gsk_" + "é".encode() * 40, "not ascii"),
        (b"gsk_" + b"a" * 20 + b" " + b"a" * 20, "contains a space"),
    ],
)
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_an_implausible_key_is_refused_without_being_echoed(
    tmp_path: Path,
    key_bytes: bytes,
    reason: str,
    anyio_backend: str,
) -> None:
    provider = provider_for(
        tmp_path,
        json_handler(completion()),
        key=key_bytes,
    )
    with pytest.raises(LLMCredentialUnavailable) as raised:
        await provider.generate(request=REQUEST, context=CONTEXT)
    assert "gsk" not in str(raised.value)


@pytest.mark.anyio
async def test_a_missing_key_file_is_a_credential_error(tmp_path: Path) -> None:
    provider = GroqLLMProvider(
        api_key_file=tmp_path / "absent",
        model="qwen/qwen3.6-27b",
        resolver=FakeResolver(),
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, json=completion())),
    )
    with pytest.raises(LLMCredentialUnavailable):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, LLMCredentialUnavailable),
        (403, LLMCredentialUnavailable),
        (429, LLMRateLimited),
        # A token budget larger than the credential allows. Waiting does not clear it,
        # so it must not be filed as a rate limit the caller should back off from.
        (413, LLMRequestTooLarge),
        (408, LLMTransportFailure),
        (500, LLMTransportFailure),
        (503, LLMTransportFailure),
        (302, LLMProviderRefused),
        (400, LLMProviderRefused),
        (404, LLMProviderRefused),
    ],
)
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_each_status_maps_to_its_own_error(
    tmp_path: Path,
    status_code: int,
    expected: type[Exception],
    anyio_backend: str,
) -> None:
    provider = provider_for(tmp_path, json_handler({"error": "x"}, status_code=status_code))
    with pytest.raises(expected):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_rate_limiting_logs_retry_after_and_nothing_else(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = provider_for(
        tmp_path,
        json_handler({"error": "rate limited"}, status_code=429, headers={"retry-after": "42"}),
    )
    with caplog.at_level(logging.WARNING), pytest.raises(LLMRateLimited):
        await provider.generate(request=REQUEST, context=CONTEXT)

    record = next(r for r in caplog.records if r.message == "Groq is rate limiting this credential")
    assert record.retry_after == 42
    assert "gsk" not in caplog.text


@pytest.mark.anyio
async def test_a_timeout_is_not_a_transport_failure(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("too slow", request=request)

    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMCallTimeout):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_network_error_is_a_transport_failure(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("unreachable", request=request)

    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMTransportFailure):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_tool_calls_are_parsed_and_their_action_class_is_imposed(tmp_path: Path) -> None:
    handler = json_handler(
        completion(
            text="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "getJiraIssue",
                        # Arguments arrive as a JSON *string*, so this is a parse.
                        "arguments": '{"issueIdOrKey": "KAN-1"}',
                    },
                }
            ],
        )
    )
    provider = provider_for(tmp_path, handler)

    response = await provider.generate(request=REQUEST, context=CONTEXT)

    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.tool_name == "getJiraIssue"
    assert call.arguments == {"issueIdOrKey": "KAN-1"}
    # The provider has no say in the action class -- a model that returned a mutation
    # must not be able to widen its own authority.
    assert call.action_class == ToolActionClass.READ


@pytest.mark.anyio
async def test_a_mutation_returned_by_the_model_cannot_widen_its_authority(
    tmp_path: Path,
) -> None:
    handler = json_handler(
        completion(
            text="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "createJiraIssue", "arguments": "{}"},
                    # Whatever the provider claims here is ignored.
                    "action_class": "CREATE",
                }
            ],
        )
    )
    provider = provider_for(tmp_path, handler)

    response = await provider.generate(request=REQUEST, context=CONTEXT)

    assert response.tool_calls[0].action_class == ToolActionClass.READ


@pytest.mark.anyio
@pytest.mark.parametrize(
    "arguments",
    ["not json at all", "[1, 2, 3]", '"a string"', "null"],
)
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_tool_arguments_that_are_not_an_object_are_refused(
    tmp_path: Path,
    arguments: str,
    anyio_backend: str,
) -> None:
    handler = json_handler(
        completion(
            text="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "getJiraIssue", "arguments": arguments},
                }
            ],
        )
    )
    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMInvalidResponse):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "document",
    [
        {"choices": []},
        {"choices": "not a list"},
        {"choices": [{"message": "not an object"}]},
        {"choices": [{}]},
        {},
    ],
)
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_a_malformed_completion_is_refused(
    tmp_path: Path,
    document: Any,
    anyio_backend: str,
) -> None:
    provider = provider_for(tmp_path, json_handler(document))
    with pytest.raises(LLMInvalidResponse):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_body_that_is_not_json_is_refused(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"<html>oops</html>")

    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMInvalidResponse):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_truncated_completion_is_surfaced_not_returned(tmp_path: Path) -> None:
    provider = provider_for(tmp_path, json_handler(completion(finish_reason="length")))
    # A half-written tool call or a truncated citation is worse than a clear failure.
    with pytest.raises(LLMResponseTooLarge):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_an_oversized_body_is_stopped_before_it_is_buffered(tmp_path: Path) -> None:
    oversized = b'{"padding": "' + b"x" * (MAX_RESPONSE_BYTES + 1024) + b'"}'

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=oversized)

    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMResponseTooLarge):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_an_overstated_content_length_is_refused(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=json.dumps(completion()).encode("utf-8"),
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
        )

    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMResponseTooLarge):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_compressed_body_is_refused(tmp_path: Path) -> None:
    # A genuinely gzipped body, so the refusal comes from the guard rather than from
    # a decoder choking on mislabelled bytes.
    compressed = gzip.compress(json.dumps(completion()).encode("utf-8"))

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=compressed,
            headers={"content-encoding": "gzip", "content-type": "application/json"},
        )

    provider = provider_for(tmp_path, handler)
    # Its decoded size is unbounded by anything we can measure here.
    with pytest.raises(LLMInvalidResponse):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_deeply_nested_tool_arguments_stay_inside_the_taxonomy(tmp_path: Path) -> None:
    # RecursionError is not a ValueError. Uncaught it escapes the fail-closed taxonomy
    # and surfaces as a generic 500 with a traceback -- reachable from a page whose
    # content the model was asked to relay.
    nested = '{"a":' + "[" * 5_000 + "]" * 5_000 + "}"
    assert len(nested) < MAX_TOOL_ARGUMENTS_CHARACTERS
    handler = json_handler(
        completion(
            text="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "getJiraIssue", "arguments": nested},
                }
            ],
        )
    )
    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMInvalidResponse):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_deeply_nested_body_stays_inside_the_taxonomy(tmp_path: Path) -> None:
    nested = b'{"a":' + b"[" * 5_000 + b"]" * 5_000 + b"}"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=nested)

    provider = provider_for(tmp_path, handler)
    with pytest.raises(LLMInvalidResponse):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_tool_name_that_was_never_offered_is_passed_on_not_raised(
    tmp_path: Path,
) -> None:
    # It used to raise, which killed the whole request over the most ordinary
    # mistake a model makes. The orchestration loop refuses the name against the
    # registry -- the authority -- and tells the model, so nothing reaches a
    # transport either way and the question survives.
    handler = json_handler(
        completion(
            text="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "createJiraIssue", "arguments": "{}"},
                }
            ],
        )
    )
    provider = provider_for(tmp_path, handler)

    response = await provider.generate(
        request=REQUEST.model_copy(update={"allowed_tool_names": ("getJiraIssue",)}),
        context=CONTEXT,
    )

    assert response.tool_calls[0].tool_name == "createJiraIssue"
    # Still bounded and character-checked like any other name.
    assert response.tool_calls[0].call_id == "call_1"


@pytest.mark.anyio
async def test_an_offered_tool_name_passes_the_boundary_check(tmp_path: Path) -> None:
    handler = json_handler(
        completion(
            text="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "getJiraIssue", "arguments": "{}"},
                }
            ],
        )
    )
    provider = provider_for(tmp_path, handler)

    response = await provider.generate(
        request=REQUEST.model_copy(update={"allowed_tool_names": ("getJiraIssue",)}),
        context=CONTEXT,
    )

    assert response.tool_calls[0].tool_name == "getJiraIssue"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "call_id",
    [
        # Absent: the orchestration loop has to echo this back on the result
        # message, so a call without one cannot be answered at all.
        None,
        "",
        "c" * (MAX_TOOL_CALL_ID_CHARACTERS + 1),
        # Replayed verbatim into the next request body, so a value carrying a
        # newline or a control character is refused rather than merely bounded.
        "call_1\ncall_2",
        "call\x00_1",
        "call 1",
    ],
)
async def test_an_unusable_tool_call_id_is_refused(tmp_path: Path, call_id: Any) -> None:
    call: dict[str, Any] = {
        "type": "function",
        "function": {"name": "getJiraIssue", "arguments": "{}"},
    }
    if call_id is not None:
        call["id"] = call_id
    provider = provider_for(tmp_path, json_handler(completion(text="", tool_calls=[call])))

    with pytest.raises(LLMInvalidResponse):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_the_tool_call_id_is_carried_through(tmp_path: Path) -> None:
    handler = json_handler(
        completion(
            text="",
            tool_calls=[
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "getJiraIssue", "arguments": "{}"},
                }
            ],
        )
    )
    provider = provider_for(tmp_path, handler)

    response = await provider.generate(request=REQUEST, context=CONTEXT)

    assert response.tool_calls[0].call_id == "call_abc123"


@pytest.mark.anyio
async def test_reasoning_left_in_the_answer_never_reaches_the_text(tmp_path: Path) -> None:
    # Honouring reasoning_format is the model's choice, and the configured model is a
    # free-form string. A substituted model must degrade to a plain answer rather than
    # leak its chain of thought into whatever renders the text.
    leaked = "<think>The user asked about Jira. I should recall...</think>Jira suit les tickets."
    provider = provider_for(tmp_path, json_handler(completion(text=leaked)))

    response = await provider.generate(request=REQUEST, context=CONTEXT)

    assert response.text == "Jira suit les tickets."
    assert "<think>" not in response.text


@pytest.mark.anyio
async def test_an_unterminated_reasoning_block_takes_everything_after_it(tmp_path: Path) -> None:
    provider = provider_for(
        tmp_path,
        json_handler(completion(text="Réponse courte.<think>et un raisonnement jamais fermé")),
    )

    response = await provider.generate(request=REQUEST, context=CONTEXT)

    assert response.text == "Réponse courte."


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("too_many_calls", None),
        ("name_too_long", None),
        ("arguments_too_long", None),
    ],
)
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_each_declared_tool_bound_is_enforced(
    tmp_path: Path,
    field: str,
    value: None,
    anyio_backend: str,
) -> None:
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "getJiraIssue", "arguments": "{}"},
    }
    if field == "too_many_calls":
        calls = [call] * (MAX_TOOL_CALLS + 1)
        expected: type[Exception] = LLMResponseTooLarge
    elif field == "name_too_long":
        long_name = "g" * (MAX_TOOL_NAME_CHARACTERS + 1)
        calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": long_name, "arguments": "{}"},
            }
        ]
        expected = LLMInvalidResponse
    else:
        long_arguments = '{"k":"' + "v" * MAX_TOOL_ARGUMENTS_CHARACTERS + '"}'
        calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "getJiraIssue", "arguments": long_arguments},
            }
        ]
        expected = LLMResponseTooLarge

    provider = provider_for(tmp_path, json_handler(completion(text="", tool_calls=calls)))
    with pytest.raises(expected):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_long_text_under_the_byte_ceiling_is_still_refused(tmp_path: Path) -> None:
    # A distinct path from the 2 MiB body ceiling: this text passes the wire bound and
    # must be stopped by the character bound instead.
    text = "a" * (MAX_TEXT_CHARACTERS + 1)
    assert len(text.encode("utf-8")) < MAX_RESPONSE_BYTES
    provider = provider_for(tmp_path, json_handler(completion(text=text)))
    with pytest.raises(LLMResponseTooLarge):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_an_oversized_api_key_is_refused(tmp_path: Path) -> None:
    provider = provider_for(
        tmp_path,
        json_handler(completion()),
        key=b"gsk_" + b"a" * MAX_API_KEY_BYTES,
    )
    with pytest.raises(LLMCredentialUnavailable):
        await provider.generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_a_hostile_retry_after_is_not_written_verbatim_to_the_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = provider_for(
        tmp_path,
        json_handler(
            {"error": "x"},
            status_code=429,
            headers={"retry-after": "12\nWARNING intrus: compte administrateur cree"},
        ),
    )
    with caplog.at_level(logging.WARNING), pytest.raises(LLMRateLimited):
        await provider.generate(request=REQUEST, context=CONTEXT)

    record = next(r for r in caplog.records if r.message == "Groq is rate limiting this credential")
    assert record.retry_after is None
    assert "intrus" not in caplog.text


@pytest.mark.anyio
async def test_the_served_model_is_reported_apart_from_the_requested_one(
    tmp_path: Path,
) -> None:
    document = completion()
    document["model"] = "qwen/qwen3.6-27b-substituted"
    provider = provider_for(tmp_path, json_handler(document))

    response = await provider.generate(request=REQUEST, context=CONTEXT)

    assert response.model_name == "qwen/qwen3.6-27b"
    # A silent substitution stays visible rather than being assumed away.
    assert response.model_version == "qwen/qwen3.6-27b-substituted"
    assert response.text == "Deux tickets sont ouverts."
