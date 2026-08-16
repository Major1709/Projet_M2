import asyncio
from typing import Any

import pytest

from app.agent.audit import AuditedLLMProvider
from app.agent.domain import LLMRequest, LLMResponse, ProposedToolCall
from app.agent.errors import (
    LLMAuditUnavailable,
    LLMCredentialUnavailable,
    LLMDNSRejected,
    LLMError,
    LLMInvalidResponse,
    LLMProviderRefused,
    LLMRateLimited,
    LLMRequestTooLarge,
    LLMResponseTooLarge,
    LLMTransportFailure,
)
from app.audit.adapters.memory import InMemoryAuditSink
from app.audit.domain import AuditEventType
from app.core.identity import SecurityContext
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.domain import ToolActionClass
from app.mcp.ports import RemoteContentBlock, RemoteToolResult
from tests.test_mcp_read_workflow import run_call, workflow_for

CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")
MODEL = "qwen/qwen3.6-27b"


class StubProvider:
    """Stands in for any adapter. The decorator must not know which one it wraps."""

    def __init__(self, *, response: LLMResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = 0

    @property
    def model_name(self) -> str:
        return MODEL

    async def generate(self, *, request: LLMRequest, context: SecurityContext) -> LLMResponse:
        del request, context
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class BrokenSink:
    def __init__(self, *, fail_on: int = 1) -> None:
        self.fail_on = fail_on
        self.appended = 0

    def append(self, event: Any) -> None:
        del event
        self.appended += 1
        if self.appended >= self.fail_on:
            raise RuntimeError("the audit store is unreachable")


def a_response(**changes: Any) -> LLMResponse:
    values: dict[str, Any] = {"text": "Une phrase.", "model_name": MODEL}
    values.update(changes)
    return LLMResponse(**values)


def a_request(**changes: Any) -> LLMRequest:
    values: dict[str, Any] = {
        "messages": ({"role": "user", "content": "A quoi sert Jira ?"},),
        "correlation_id": "corr-llm-1",
    }
    values.update(changes)
    return LLMRequest(**values)


def audited(
    *,
    response: LLMResponse | None = None,
    error: Exception | None = None,
    sink: Any | None = None,
) -> tuple[AuditedLLMProvider, StubProvider, Any]:
    inner = StubProvider(response=response if error is None else None, error=error)
    audit_sink = sink if sink is not None else InMemoryAuditSink()
    return AuditedLLMProvider(provider=inner, audit_sink=audit_sink), inner, audit_sink


def run(provider: AuditedLLMProvider, request: LLMRequest | None = None) -> LLMResponse:
    return asyncio.run(provider.generate(request=request or a_request(), context=CONTEXT))


def types_of(sink: InMemoryAuditSink) -> list[AuditEventType]:
    return [event.event_type for event in sink.snapshot()]


def test_a_successful_call_is_authorized_then_completed() -> None:
    provider, _, sink = audited(response=a_response())

    run(provider)

    assert types_of(sink) == [
        AuditEventType.LLM_INVOCATION_AUTHORIZED,
        AuditEventType.LLM_INVOCATION_COMPLETED,
    ]


def test_the_authorization_is_written_before_the_provider_is_reached() -> None:
    # The ordering is the whole point: a crash between the two leaves a visibly
    # unterminated invocation rather than no invocation at all.
    observed: list[str] = []

    class OrderingSink:
        def append(self, event: Any) -> None:
            observed.append(f"audit:{event.event_type.value}")

    class RecordingProvider(StubProvider):
        async def generate(self, *, request: LLMRequest, context: SecurityContext) -> LLMResponse:
            observed.append("provider")
            return await super().generate(request=request, context=context)

    inner = RecordingProvider(response=a_response())
    provider = AuditedLLMProvider(provider=inner, audit_sink=OrderingSink())

    run(provider)

    assert observed == [
        "audit:LLM_INVOCATION_AUTHORIZED",
        "provider",
        "audit:LLM_INVOCATION_COMPLETED",
    ]


def test_an_unwritable_authorization_stops_the_call() -> None:
    provider, inner, _ = audited(response=a_response(), sink=BrokenSink(fail_on=1))

    with pytest.raises(LLMAuditUnavailable):
        run(provider)

    # Fail-closed means the provider is never reached, not that the failure is
    # reported after the model has already been paid for.
    assert inner.calls == 0


def test_an_unwritable_completion_still_fails_the_call() -> None:
    provider, inner, _ = audited(response=a_response(), sink=BrokenSink(fail_on=2))

    with pytest.raises(LLMAuditUnavailable):
        run(provider)

    assert inner.calls == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LLMCredentialUnavailable(), AuditEventType.LLM_INVOCATION_REFUSED),
        (LLMDNSRejected(), AuditEventType.LLM_INVOCATION_REFUSED),
        (LLMTransportFailure(), AuditEventType.LLM_INVOCATION_REFUSED),
        (LLMRateLimited(), AuditEventType.LLM_INVOCATION_REFUSED),
        (LLMProviderRefused(), AuditEventType.LLM_INVOCATION_REFUSED),
        (LLMInvalidResponse(), AuditEventType.LLM_INVOCATION_REFUSED),
        # Our own ceilings, not the provider's refusal.
        (LLMRequestTooLarge(), AuditEventType.LLM_INVOCATION_BOUNDED),
        (LLMResponseTooLarge(), AuditEventType.LLM_INVOCATION_BOUNDED),
    ],
)
def test_each_error_reaches_its_verdict(error: LLMError, expected: AuditEventType) -> None:
    provider, _, sink = audited(error=error)

    with pytest.raises(type(error)):
        run(provider)

    assert types_of(sink) == [AuditEventType.LLM_INVOCATION_AUTHORIZED, expected]
    assert sink.snapshot()[1].details["error_code"] == error.code


def test_an_unexpected_exception_is_recorded_and_not_swallowed() -> None:
    provider, _, sink = audited(error=ZeroDivisionError("defect"))

    with pytest.raises(ZeroDivisionError):
        run(provider)

    refusal = sink.snapshot()[1]
    assert refusal.event_type == AuditEventType.LLM_INVOCATION_REFUSED
    assert refusal.details["error_code"] == "LLM_UNEXPECTED_FAILURE"
    assert refusal.details["error_type"] == "ZeroDivisionError"
    # The message may carry unbounded provider text, so it is not recorded.
    assert "defect" not in str(refusal.details)


def test_the_identity_recorded_is_the_server_derived_one() -> None:
    provider, _, sink = audited(response=a_response())

    run(provider)

    for event in sink.snapshot():
        assert event.tenant_id == "tenant-a"
        assert event.actor_user_id == "user-a"


def test_the_requested_model_is_reported_apart_from_the_served_one() -> None:
    provider, _, sink = audited(response=a_response(model_version="qwen3.6-27b-build-7"))

    run(provider)

    completion = sink.snapshot()[1]
    assert completion.details["model_name"] == MODEL
    assert completion.details["model_version"] == "qwen3.6-27b-build-7"


def test_the_model_name_is_read_from_the_provider_not_configured_twice() -> None:
    provider, inner, _ = audited(response=a_response())

    assert provider.model_name == inner.model_name


def test_proposed_tool_calls_are_recorded_with_their_action_class() -> None:
    provider, _, sink = audited(
        response=a_response(
            tool_calls=(
                ProposedToolCall(
                    tool_name="getJiraIssue",
                    action_class=ToolActionClass.READ,
                    arguments={"issueIdOrKey": "KAN-1"},
                ),
            )
        )
    )

    run(provider)

    completion = sink.snapshot()[1]
    assert completion.details["tool_calls"] == [
        {"tool_name": "getJiraIssue", "action_class": "READ"}
    ]


def test_no_prompt_or_completion_text_reaches_the_trail() -> None:
    secret = "SALAIRE-CONFIDENTIEL-4711"
    provider, _, sink = audited(response=a_response(text=f"Reponse citant {secret}"))

    run(provider, a_request(messages=({"role": "user", "content": secret},)))

    # The messages carry whatever was read from Jira, Confluence or Figma; copying
    # that into the audit table would duplicate the corpus somewhere with a
    # different retention and a different audience.
    for event in sink.snapshot():
        assert secret not in str(event.details)


def test_the_prompt_fingerprint_identifies_without_disclosing() -> None:
    first, _, first_sink = audited(response=a_response())
    second, _, second_sink = audited(response=a_response())
    other, _, other_sink = audited(response=a_response())

    run(first)
    run(second)
    run(other, a_request(messages=({"role": "user", "content": "Autre question"},)))

    same = {sink.snapshot()[0].details["prompt_sha256"] for sink in (first_sink, second_sink)}
    assert len(same) == 1
    assert other_sink.snapshot()[0].details["prompt_sha256"] not in same


def test_an_unserialisable_prompt_does_not_break_the_trail() -> None:
    # Failing to fingerprint must never be the reason a call is refused.
    provider, _, sink = audited(response=a_response())

    run(provider, a_request(messages=({"role": "user", "content": object()},)))

    assert len(sink.snapshot()[0].details["prompt_sha256"]) == 64


def test_the_declared_ceilings_are_recorded() -> None:
    provider, _, sink = audited(response=a_response())

    run(provider, a_request(max_completion_tokens=512, max_steps=3, tools=({"a": 1},)))

    authorization = sink.snapshot()[0].details
    assert authorization["max_completion_tokens"] == 512
    assert authorization["max_steps"] == 3
    assert authorization["message_count"] == 1
    assert authorization["tool_count"] == 1


def test_a_bounded_call_records_the_ceiling_it_hit() -> None:
    provider, _, sink = audited(error=LLMResponseTooLarge())

    with pytest.raises(LLMResponseTooLarge):
        run(provider, a_request(max_completion_tokens=2048))

    verdict = sink.snapshot()[1]
    assert verdict.event_type == AuditEventType.LLM_INVOCATION_BOUNDED
    assert verdict.details["max_completion_tokens"] == 2048


def test_every_verdict_carries_a_duration() -> None:
    provider, _, sink = audited(response=a_response())

    run(provider)

    assert sink.snapshot()[1].details["duration_ms"] >= 0


def test_one_correlation_id_ties_the_model_call_to_the_reads_it_caused() -> None:
    # The end-to-end claim: an answer is reconstructable from the trail alone --
    # the question, the model call, and the read that followed from it -- because
    # all three carry the identifier the caller supplied.
    sink = InMemoryAuditSink()
    workflow, _, _ = workflow_for(
        SourceSystem.JIRA,
        "getJiraIssue",
        result=RemoteToolResult(
            content=(RemoteContentBlock(kind="text", text="{}"),),
            structured_content=None,
        ),
        audit_sink=sink,
    )
    provider = AuditedLLMProvider(
        provider=StubProvider(
            response=a_response(
                tool_calls=(
                    ProposedToolCall(
                        tool_name="getJiraIssue",
                        action_class=ToolActionClass.READ,
                        arguments={"issueIdOrKey": "KAN-1"},
                    ),
                )
            )
        ),
        audit_sink=sink,
    )

    run(provider, a_request(correlation_id="corr-test-1"))
    run_call(
        workflow,
        source_system=SourceSystem.JIRA,
        tool_name="getJiraIssue",
        arguments={"issueIdOrKey": "KAN-1"},
    )

    trail = sink.snapshot()
    assert {event.correlation_id for event in trail} == {"corr-test-1"}
    assert types_of(sink) == [
        AuditEventType.LLM_INVOCATION_AUTHORIZED,
        AuditEventType.LLM_INVOCATION_COMPLETED,
        AuditEventType.MCP_READ_AUTHORIZED,
        AuditEventType.MCP_READ_COMPLETED,
    ]
