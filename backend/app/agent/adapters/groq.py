"""Groq chat-completions adapter behind the provider-neutral ``LLMProvider``.

Groq speaks the OpenAI chat-completions shape, so this adapter is a direct HTTP
client rather than a vendor SDK: one dependency fewer, and the request shape stays
legible next to the wire format it mirrors.

The destination is pinned here, not configured. An endpoint that could be pointed
elsewhere by an environment variable is an endpoint that can be pointed at an
attacker's server -- and it would carry the API key with it on the first request.
Pinning costs nothing (there is exactly one Groq) and removes that lever entirely,
the same reasoning that fixed the Atlassian and Figma endpoints in the registry.

What comes back is untrusted. The model's own output is data, and so is every byte
around it: the response is bounded before it is buffered, the tool-call arguments
are parsed as JSON rather than trusted as a shape, and the action class is imposed
by this adapter instead of being read from what the provider returned.
"""

import json
import logging
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

import anyio
import httpx2

from app.agent.domain import LLMRequest, LLMResponse, ProposedToolCall
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
from app.core.identity import SecurityContext
from app.mcp.adapters.http_guard import (
    CONNECT_TIMEOUT_SECONDS,
    HTTPS_PORT,
    EndpointResolver,
    SystemEndpointResolver,
    bounded_response_hook,
    is_approved_public_address,
    validate_fixed_endpoint,
)
from app.mcp.domain import ToolActionClass
from app.mcp.errors import MCPInvalidResponse, MCPResponseTooLarge

logger = logging.getLogger(__name__)

GROQ_ENDPOINT: Final = "https://api.groq.com/openai/v1"
# Checked at import so a malformed destination fails the process at start-up rather
# than on the first inference.
validate_fixed_endpoint(GROQ_ENDPOINT)

# An inference can legitimately take far longer than a document read, so the call
# ceiling is its own value rather than the MCP one. The connect ceiling is not:
# reaching Groq should be as quick as reaching anything else.
CALL_TIMEOUT_SECONDS: Final = 120.0

# qwen3.6-27b caps completions at 16 384 tokens. This is a ceiling the adapter
# applies to whatever the caller asks for -- the ask is lowered to fit, not refused.
# Getting a shorter completion is better than a request the provider rejects
# outright, and the truncation that would follow is caught by ``finish_reason``.
MAX_COMPLETION_TOKENS: Final = 16_384

# A completion bounded at 16 384 tokens cannot honestly exceed a couple of megabytes
# once JSON-encoded. The shared 12 MiB MCP ceiling would let a misbehaving provider
# push forty times more than that into memory before anything noticed.
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024

# Bounds on the untrusted parts of the answer, applied before anything is parsed.
MAX_TEXT_CHARACTERS: Final = 200_000
MAX_TOOL_CALLS: Final = 8
MAX_TOOL_ARGUMENTS_CHARACTERS: Final = 20_000
MAX_TOOL_NAME_CHARACTERS: Final = 200
# The provider's own handle for a proposed call. An OpenAI-shaped endpoint requires
# it back on the result message, so the orchestration loop cannot answer a call
# without it -- which is why a tool call arriving without one is a malformed answer
# rather than something to paper over with a generated identifier.
MAX_TOOL_CALL_ID_CHARACTERS: Final = 128

MIN_API_KEY_BYTES: Final = 16
MAX_API_KEY_BYTES: Final = 4096

_REASONING_OPEN: Final = "<think>"
_REASONING_CLOSE: Final = "</think>"


def _validated_api_key(raw: bytes) -> str:
    """Accept a plausible API key without ever echoing it.

    Only the length and the byte class are inspected. The value is never logged,
    never returned in an error, and never compared against a literal, so a wrong key
    produces a refusal from Groq rather than a diagnostic from us.
    """

    try:
        decoded = raw.rstrip(b"\r\n").decode("ascii")
    except UnicodeDecodeError as error:
        raise LLMCredentialUnavailable() from error
    key = decoded.strip()
    encoded = key.encode("ascii", errors="replace")
    if (
        len(encoded) < MIN_API_KEY_BYTES
        or len(encoded) > MAX_API_KEY_BYTES
        or any(byte < 0x21 or byte > 0x7E for byte in encoded)
    ):
        raise LLMCredentialUnavailable()
    return key


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if content is None:
        return ""
    if not isinstance(content, str):
        raise LLMInvalidResponse()
    if len(content) > MAX_TEXT_CHARACTERS:
        raise LLMResponseTooLarge()
    return _without_reasoning(content)


def _without_reasoning(content: str) -> str:
    """Drop any <think> block a model wrote into the answer despite the request.

    The request asks for reasoning in its own field, but honouring that is the
    model's choice, and the configured model is a free-form string. Stripping here
    means a substituted model degrades to a plain answer rather than leaking its
    chain of thought into whatever renders the text.
    """

    while True:
        opening = content.find(_REASONING_OPEN)
        if opening == -1:
            return content.strip()
        closing = content.find(_REASONING_CLOSE, opening)
        if closing == -1:
            # Unterminated: everything from the tag onward is reasoning.
            return content[:opening].strip()
        content = content[:opening] + content[closing + len(_REASONING_CLOSE) :]


def _tool_calls_of(
    message: dict[str, Any],
    allowed_tool_names: tuple[str, ...],
) -> tuple[ProposedToolCall, ...]:
    """Rebuild the model's tool calls, treating every field as untrusted input.

    ``allowed_tool_names`` is enforced here when the caller supplies one. It does not
    replace the registry allowlist further down -- that one stays the authority -- but
    a name that was never offered is a malformed answer, and saying so at the boundary
    beats carrying it deeper to be refused with less context.
    """

    raw_calls = message.get("tool_calls")
    if raw_calls is None:
        return ()
    if not isinstance(raw_calls, list):
        raise LLMInvalidResponse()
    if len(raw_calls) > MAX_TOOL_CALLS:
        raise LLMResponseTooLarge()

    calls: list[ProposedToolCall] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise LLMInvalidResponse()
        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise LLMInvalidResponse()

        # Echoed back verbatim on the result message, so it is constrained to
        # printable ASCII rather than merely bounded: a value carrying a newline or
        # a control character would be replayed into the next request body.
        call_id = raw_call.get("id")
        if (
            not isinstance(call_id, str)
            or not call_id
            or len(call_id) > MAX_TOOL_CALL_ID_CHARACTERS
            or not all("\x21" <= character <= "\x7e" for character in call_id)
        ):
            raise LLMInvalidResponse()

        name = function.get("name")
        if not isinstance(name, str) or not name or len(name) > MAX_TOOL_NAME_CHARACTERS:
            raise LLMInvalidResponse()
        if allowed_tool_names and name not in allowed_tool_names:
            raise LLMInvalidResponse()

        # OpenAI-shaped providers return the arguments as a JSON *string*, so this is
        # a parse, not a cast. Anything that is not an object is refused rather than
        # coerced: a bare list or scalar reaching the read workflow would fail its
        # schema check later and much less clearly.
        raw_arguments = function.get("arguments", "{}")
        if not isinstance(raw_arguments, str):
            raise LLMInvalidResponse()
        if len(raw_arguments) > MAX_TOOL_ARGUMENTS_CHARACTERS:
            raise LLMResponseTooLarge()
        try:
            arguments = json.loads(raw_arguments or "{}")
        except (ValueError, RecursionError) as error:
            # A deeply nested document exhausts the parser's stack and raises
            # RecursionError, which is not a ValueError. Left uncaught it escapes the
            # fail-closed taxonomy entirely and surfaces as a generic 500 with a
            # traceback -- reachable from a page whose content the model was asked to
            # relay, so it is untrusted input like everything else here.
            raise LLMInvalidResponse() from error
        if not isinstance(arguments, dict):
            raise LLMInvalidResponse()

        calls.append(
            ProposedToolCall(
                call_id=call_id,
                tool_name=name,
                # Imposed, never parsed. The provider has no say in the action class:
                # this release performs reads only, and a model that returned
                # anything else must not be able to widen its own authority.
                action_class=ToolActionClass.READ,
                arguments=arguments,
            )
        )
    return tuple(calls)


class GroqLLMProvider:
    """Chat completions against a pinned Groq endpoint. The API key never leaves here."""

    def __init__(
        self,
        *,
        api_key_file: Path,
        model: str,
        max_completion_tokens: int = MAX_COMPLETION_TOKENS,
        resolver: EndpointResolver | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if not model:
            raise ValueError("A Groq model must be named")
        if max_completion_tokens < 1:
            raise ValueError("The completion ceiling must be positive")
        self._api_key_file = api_key_file
        self._model = model
        # ``min`` rather than a validation error: a caller asking for more than the
        # model can produce is asking for a truncation, and silently getting less is
        # better than a request the provider would reject outright.
        self._max_completion_tokens = min(max_completion_tokens, MAX_COMPLETION_TOKENS)
        self._resolver = resolver or SystemEndpointResolver()
        self._transport = transport

    @property
    def model_name(self) -> str:
        """The model this provider asks for, as opposed to the one served.

        Exposed so the audit decorator reads it from the provider instead of being
        told it separately: two configured copies of the same fact drift, and a
        trail naming a model the adapter never requested is worse than none.
        """

        return self._model

    async def generate(
        self,
        *,
        request: LLMRequest,
        context: SecurityContext,
    ) -> LLMResponse:
        await self._reject_unapproved_address()
        api_key = await self._api_key()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": list(request.messages),
            # The caller's ask, capped by ours. The adapter's value is a ceiling, not
            # a quota to spend: a provider charges the requested budget against the
            # credential's allowance whether or not the completion uses it.
            "max_tokens": min(request.max_completion_tokens, self._max_completion_tokens),
            # qwen3.6-27b reasons before answering, and by default writes that
            # reasoning into the answer inside <think> tags. Asking for it parsed puts
            # it in its own field, so the user-facing text stays the answer.
            #
            # This holds for models that honour the parameter, which is a property of
            # the configured model rather than of this adapter. A model that ignored
            # it would put its reasoning back into ``content`` -- and from there into a
            # rendered answer -- which is why ``_text_of`` strips the tags defensively
            # rather than trusting the request to have been respected.
            "reasoning_format": "parsed",
        }
        if request.tools:
            payload["tools"] = list(request.tools)

        timeout = httpx2.Timeout(
            CALL_TIMEOUT_SECONDS,
            connect=CONNECT_TIMEOUT_SECONDS,
            read=CALL_TIMEOUT_SECONDS,
            write=CALL_TIMEOUT_SECONDS,
            pool=CONNECT_TIMEOUT_SECONDS,
        )
        client = httpx2.AsyncClient(
            base_url=GROQ_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                # Identity encoding keeps the byte ceiling meaningful: a compressed
                # body's decoded size is unbounded by anything measurable on the wire.
                "Accept-Encoding": "identity",
            },
            timeout=timeout,
            # No redirects: a 3xx would re-issue the request, and the Authorization
            # header with it, against a destination we never approved.
            follow_redirects=False,
            trust_env=False,
            transport=self._transport,
            event_hooks={"response": [bounded_response_hook(MAX_RESPONSE_BYTES)]},
        )
        async with client:
            document = await self._post(client, payload, request.correlation_id)
        return self._normalize(document, request.allowed_tool_names)

    async def _reject_unapproved_address(self) -> None:
        """Resolve the pinned host and refuse anything that is not publicly routable.

        Done before the key is read, so a hijacked resolver never reaches a process
        that is holding the credential in memory.
        """

        hostname = urlsplit(GROQ_ENDPOINT).hostname
        if hostname is None:  # pragma: no cover - the endpoint is checked at import
            raise LLMDNSRejected()
        try:
            addresses = await self._resolver.resolve(hostname=hostname, port=HTTPS_PORT)
        except Exception as error:
            raise LLMDNSRejected() from error
        if not addresses or any(not is_approved_public_address(address) for address in addresses):
            raise LLMDNSRejected()

    async def _api_key(self) -> str:
        try:
            raw = await anyio.to_thread.run_sync(self._api_key_file.read_bytes)
        except OSError as error:
            raise LLMCredentialUnavailable() from error
        return _validated_api_key(raw)

    async def _post(
        self,
        client: httpx2.AsyncClient,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        try:
            response = await client.post("/chat/completions", json=payload)
        except httpx2.TimeoutException as error:
            raise LLMCallTimeout() from error
        except MCPResponseTooLarge as error:
            # The shared guards speak the MCP taxonomy because that is where they were
            # extracted from. Translating at this boundary keeps one implementation of
            # the byte ceiling while letting the orchestration layer see one taxonomy.
            raise LLMResponseTooLarge() from error
        except MCPInvalidResponse as error:
            raise LLMInvalidResponse() from error
        except httpx2.DecodingError as error:
            # A body we cannot decode is a malformed answer, not a broken network.
            raise LLMInvalidResponse() from error
        except httpx2.HTTPError as error:
            raise LLMTransportFailure() from error

        if response.status_code in {401, 403}:
            raise LLMCredentialUnavailable()
        if response.status_code == 429:
            # A quota is not an outage. Filing it under a transport failure would send
            # the operator hunting a network problem that does not exist, and would
            # discard the one actionable value in the answer.
            # Parsed before it is logged. The value is provider-controlled, and a raw
            # header written verbatim into a log line is a log-injection primitive for
            # any sink that does not escape.
            raw_retry_after = response.headers.get("retry-after", "")
            retry_after = int(raw_retry_after) if raw_retry_after.strip().isdigit() else None
            logger.warning(
                "Groq is rate limiting this credential",
                extra={"llm_provider": "groq", "retry_after": retry_after},
            )
            raise LLMRateLimited()
        if response.status_code == 413:
            # Groq labels this a rate limit, but waiting does not clear it: the
            # request's own budget -- prompt plus completion ceiling -- is larger than
            # the credential may spend in a window. The caller has to send less.
            logger.warning(
                "Groq refused the request as too large for this credential",
                extra={"llm_provider": "groq", "correlation_id": correlation_id},
            )
            raise LLMRequestTooLarge()
        if response.status_code == 408 or response.status_code >= 500:
            raise LLMTransportFailure()
        if response.status_code != 200:
            logger.warning(
                "Groq refused the completion",
                extra={
                    "llm_provider": "groq",
                    "status_code": response.status_code,
                    "correlation_id": correlation_id,
                },
            )
            raise LLMProviderRefused()

        try:
            document = response.json()
        except (ValueError, RecursionError) as error:
            raise LLMInvalidResponse() from error
        if not isinstance(document, dict):
            raise LLMInvalidResponse()
        return document

    def _normalize(
        self,
        document: dict[str, Any],
        allowed_tool_names: tuple[str, ...],
    ) -> LLMResponse:
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMInvalidResponse()
        first = choices[0]
        if not isinstance(first, dict):
            raise LLMInvalidResponse()
        message = first.get("message")
        if not isinstance(message, dict):
            raise LLMInvalidResponse()

        if first.get("finish_reason") == "length":
            # The completion ran into the ceiling. Surfaced rather than returned as a
            # whole answer, because a truncated tool call or a half-written citation
            # is worse than an explicit failure. On a reasoning model this is most
            # often the thinking having consumed the budget before the answer began.
            raise LLMResponseTooLarge()

        served_model = document.get("model")
        return LLMResponse(
            text=_text_of(message),
            tool_calls=_tool_calls_of(message, allowed_tool_names),
            model_name=self._model,
            # What the provider says it served, kept apart from what we asked for so a
            # silent substitution is visible rather than assumed away.
            model_version=served_model if isinstance(served_model, str) else None,
        )
