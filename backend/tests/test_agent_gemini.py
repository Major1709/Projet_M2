"""What is true of Gemini and of no other provider.

The wire handling -- bounds, tool-call parsing, error taxonomy -- is the shared
socle, and ``test_agent_groq`` already holds it to sixty assertions. Repeating those
here against a different endpoint would prove nothing new and would rot in a
different direction. So this file covers only the seam: where the requests go, what
this adapter must not send, and how the configuration refuses an ambiguous switch.
"""

import json
import logging
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.agent.adapters.gemini import (
    GEMINI_ENDPOINT,
    MAX_COMPLETION_TOKENS,
    GeminiLLMProvider,
)
from app.agent.adapters.groq import GROQ_ENDPOINT, GroqLLMProvider
from app.agent.domain import LLMRequest
from app.agent.errors import LLMRateLimited
from app.bootstrap import _build_llm_provider
from app.core.config import Settings
from app.core.identity import SecurityContext

CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")
REQUEST = LLMRequest(
    messages=({"role": "user", "content": "Quels tickets sont ouverts ?"},),
    correlation_id="corr-1",
)


class FakeResolver:
    async def resolve(self, *, hostname: str, port: int) -> tuple[str, ...]:
        return ("93.184.216.34",)


def api_key_file(tmp_path: Path, name: str = "gemini_api_key") -> Path:
    path = tmp_path / name
    path.write_bytes(b"AIza" + b"b" * 35 + b"\n")
    return path


def recording_handler(document: Any, *, status_code: int = 200, headers=None):
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx2.Response(
            status_code,
            content=json.dumps(document).encode("utf-8"),
            headers={"content-type": "application/json", **(headers or {})},
        )

    return handler, seen


def provider_for(tmp_path: Path, handler, **kwargs) -> GeminiLLMProvider:
    return GeminiLLMProvider(
        api_key_file=api_key_file(tmp_path),
        model=kwargs.pop("model", "gemini-3.5-flash-lite"),
        resolver=FakeResolver(),
        transport=httpx2.MockTransport(handler),
        **kwargs,
    )


COMPLETION: dict[str, Any] = {
    "model": "gemini-3.5-flash-lite",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Deux tickets sont ouverts."},
        }
    ],
}


def test_the_destination_is_pinned_and_is_not_groq() -> None:
    """The property the whole endpoint-pinning design exists to hold.

    Asserted against a literal rather than against the constant it came from: a
    comparison to itself would still pass if someone edited the constant.
    """

    assert GEMINI_ENDPOINT == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert GeminiLLMProvider.ENDPOINT != GroqLLMProvider.ENDPOINT
    assert GeminiLLMProvider.HOSTNAME == "generativelanguage.googleapis.com"


@pytest.mark.anyio
async def test_the_request_reaches_the_gemini_completions_path(tmp_path: Path) -> None:
    handler, seen = recording_handler(COMPLETION)

    await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)

    assert seen["url"] == f"{GEMINI_ENDPOINT}/chat/completions"
    assert GROQ_ENDPOINT not in seen["url"]


@pytest.mark.anyio
async def test_the_groq_only_reasoning_field_is_never_sent(tmp_path: Path) -> None:
    """The reason ``EXTRA_PAYLOAD`` belongs to the subclass and not to the socle.

    Gemini's compatibility layer refuses a request carrying a field it does not
    know, so this is not a tidiness check -- sending it would break every call.
    """

    handler, seen = recording_handler(COMPLETION)

    await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)

    assert "reasoning_format" not in seen["payload"]
    assert seen["payload"]["model"] == "gemini-3.5-flash-lite"
    assert seen["payload"]["messages"] == [dict(REQUEST.messages[0])]


@pytest.mark.anyio
async def test_a_caller_cannot_raise_the_completion_ceiling(tmp_path: Path) -> None:
    """The adapter's ceiling is a bound, not a default a caller can argue with."""

    handler, seen = recording_handler(COMPLETION)
    # 16 384 is the largest a caller may even ask for -- ``LLMRequest`` refuses more --
    # and it is twice the Gemini ceiling, which is the gap this test exists to close.
    ask = 16_384
    assert ask > MAX_COMPLETION_TOKENS
    provider = provider_for(tmp_path, handler, max_completion_tokens=ask)

    await provider.generate(
        request=LLMRequest(
            messages=REQUEST.messages,
            correlation_id="corr-2",
            max_completion_tokens=ask,
        ),
        context=CONTEXT,
    )

    assert seen["payload"]["max_tokens"] == MAX_COMPLETION_TOKENS


@pytest.mark.anyio
async def test_a_rate_limit_names_gemini_in_the_trail(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The socle logs one message for every provider, so the label is what tells them apart."""

    handler, _ = recording_handler({}, status_code=429, headers={"retry-after": "42"})

    with caplog.at_level(logging.WARNING), pytest.raises(LLMRateLimited):
        await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)

    record = next(
        r
        for r in caplog.records
        if r.message == "The model provider is rate limiting this credential"
    )
    assert record.llm_provider == "gemini"
    assert record.retry_after == 42


def test_enabling_both_providers_is_refused(tmp_path: Path) -> None:
    """No precedence rule, because a silent winner is how the wrong dashboard gets read."""

    with pytest.raises(ValueError, match="exactly one model provider"):
        Settings(
            environment="test",
            llm_groq_enabled=True,
            llm_groq_api_key_file=api_key_file(tmp_path, "groq_key"),
            llm_gemini_enabled=True,
            llm_gemini_api_key_file=api_key_file(tmp_path),
        )


def test_gemini_without_a_key_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PKA_LLM_GEMINI_API_KEY_FILE"):
        Settings(environment="test", llm_gemini_enabled=True)


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [("groq", GroqLLMProvider), ("gemini", GeminiLLMProvider), (None, type(None))],
)
def test_the_container_builds_the_provider_the_configuration_names(
    tmp_path: Path, enabled: str | None, expected: type
) -> None:
    """The switch, end to end. Rolling back is this one flag and nothing else."""

    flags: dict[str, Any] = {}
    if enabled is not None:
        flags[f"llm_{enabled}_enabled"] = True
        flags[f"llm_{enabled}_api_key_file"] = api_key_file(tmp_path, f"{enabled}_key")

    provider = _build_llm_provider(Settings(environment="test", **flags))

    assert isinstance(provider, expected)


def test_the_configured_model_is_the_one_the_provider_asks_for(tmp_path: Path) -> None:
    """``model_name`` feeds the audit trail, so a trail naming a model nobody
    requested would be worse than none."""

    settings = Settings(
        environment="test",
        llm_gemini_enabled=True,
        llm_gemini_api_key_file=api_key_file(tmp_path),
        llm_gemini_model="gemini-3.5-flash-lite",
    )

    assert _build_llm_provider(settings).model_name == "gemini-3.5-flash-lite"


# --- La signature de pensee -------------------------------------------------------
#
# Gemini 3.x raisonne avant d'appeler un outil, renvoie une signature opaque avec
# l'appel, et refuse en HTTP 400 le tour suivant si elle ne lui revient pas. Le format
# OpenAI n'a pas de champ pour cela : Google le passe dans ``extra_content``. Constate
# contre l'API reelle le 01/09/2026, apres une lecture MCP pourtant reussie -- l'echec
# ne se voyait donc qu'au second appel.


def tool_call_with(extra: Any) -> dict[str, Any]:
    call: dict[str, Any] = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "getJiraIssue", "arguments": '{"issueIdOrKey":"KAN-2"}'},
    }
    if extra is not None:
        call["extra_content"] = extra
    return call


def completion_with(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "gemini-3.5-flash-lite",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {"role": "assistant", "tool_calls": [call]},
            }
        ],
    }


SIGNATURE = {"google": {"thought_signature": "El4KXAERTTIP3xRP"}}


@pytest.mark.anyio
async def test_the_thought_signature_is_captured_whole(tmp_path: Path) -> None:
    """Kept as the provider sent it, not reached into. The adapter does not know what
    is in there and must not learn."""

    handler, _ = recording_handler(completion_with(tool_call_with(SIGNATURE)))

    answer = await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)

    assert answer.tool_calls[0].provider_continuation == SIGNATURE


@pytest.mark.anyio
async def test_the_signature_returns_on_the_next_turn(tmp_path: Path) -> None:
    """The property that fixes the 400. Built through the real workflow helper rather
    than asserted on a hand-written dictionary, because the helper is what runs."""

    from app.agent.read_workflow import AgentReadWorkflow

    handler, _ = recording_handler(completion_with(tool_call_with(SIGNATURE)))
    answer = await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)

    turn = AgentReadWorkflow._assistant_turn(answer.text, answer.tool_calls)

    assert turn["tool_calls"][0]["extra_content"] == SIGNATURE


@pytest.mark.anyio
async def test_a_provider_that_sends_no_signature_produces_no_field(tmp_path: Path) -> None:
    """Groq sends nothing here, and an empty ``extra_content`` is not the same as none:
    the key must be absent, not present and null."""

    from app.agent.read_workflow import AgentReadWorkflow

    handler, _ = recording_handler(completion_with(tool_call_with(None)))
    answer = await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)

    assert answer.tool_calls[0].provider_continuation is None
    assert "extra_content" not in AgentReadWorkflow._assistant_turn("", answer.tool_calls)[
        "tool_calls"
    ][0]


@pytest.mark.anyio
@pytest.mark.parametrize("hostile", ["une chaine", ["une", "liste"], 42])
async def test_a_signature_that_is_not_an_object_is_refused(
    tmp_path: Path, hostile: Any
) -> None:
    """It goes back into a request, so its shape is checked even though its content is
    never read."""

    from app.agent.errors import LLMInvalidResponse

    handler, _ = recording_handler(completion_with(tool_call_with(hostile)))

    with pytest.raises(LLMInvalidResponse):
        await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)


@pytest.mark.anyio
async def test_an_unbounded_signature_is_refused(tmp_path: Path) -> None:
    """"The provider sent it" is not a reason to buffer an unbounded string."""

    from app.agent.adapters.openai_compatible import MAX_TOOL_CONTINUATION_CHARACTERS
    from app.agent.errors import LLMResponseTooLarge

    enorme = {"google": {"thought_signature": "A" * (MAX_TOOL_CONTINUATION_CHARACTERS + 1)}}
    handler, _ = recording_handler(completion_with(tool_call_with(enorme)))

    with pytest.raises(LLMResponseTooLarge):
        await provider_for(tmp_path, handler).generate(request=REQUEST, context=CONTEXT)
