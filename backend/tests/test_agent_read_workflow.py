import asyncio
import json
from typing import Any

import pytest

from app.agent.domain import LLMRequest, LLMResponse, ProposedToolCall
from app.agent.errors import LLMRateLimited
from app.agent.read_workflow import (
    MAX_OBSERVATION_CHARACTERS,
    AgentQuestion,
    AgentReadWorkflow,
    AgentStopReason,
    tool_catalogue,
)
from app.core.identity import SecurityContext
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.domain import ToolActionClass
from app.mcp.errors import (
    MCPAuditUnavailable,
    MCPDNSRejected,
    MCPGrantUnavailable,
    MCPInputRejected,
    MCPProviderDisabled,
    MCPRateLimited,
    MCPRemoteToolFailure,
    MCPResponseTooLarge,
    MCPSchemaRejected,
    MCPToolDenied,
    MCPTransportFailure,
)
from app.mcp.ports import RemoteContentBlock, RemoteToolResult
from app.mcp.registry import MCPToolRegistry
from tests.test_mcp_read_workflow import workflow_for

CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")
MODEL = "qwen/qwen3.6-27b"


class ScriptedProvider:
    """Replays a fixed sequence of model turns and records what it was shown."""

    def __init__(self, *turns: LLMResponse | Exception) -> None:
        self.turns = list(turns)
        self.requests: list[LLMRequest] = []

    @property
    def model_name(self) -> str:
        return MODEL

    async def generate(self, *, request: LLMRequest, context: SecurityContext) -> LLMResponse:
        del context
        self.requests.append(request)
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


class RefusingReads:
    """Stands in for MCPReadWorkflow when the read is meant to fail."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[Any] = []

    async def execute_call(self, *, call: Any, context: SecurityContext) -> Any:
        del context
        self.calls.append(call)
        raise self.error


def answered(text: str) -> LLMResponse:
    return LLMResponse(text=text, model_name=MODEL)


def proposing(
    tool_name: str = "getJiraIssue",
    arguments: dict[str, Any] | None = None,
    *,
    call_id: str = "call_1",
) -> LLMResponse:
    return LLMResponse(
        text="",
        model_name=MODEL,
        tool_calls=(
            ProposedToolCall(
                call_id=call_id,
                tool_name=tool_name,
                action_class=ToolActionClass.READ,
                arguments=arguments if arguments is not None else {"issueIdOrKey": "KAN-1"},
            ),
        ),
    )


def jira_reads(text: str = '{"key": "KAN-1"}'):
    workflow, _, _ = workflow_for(
        SourceSystem.JIRA,
        "getJiraIssue",
        result=RemoteToolResult(
            content=(RemoteContentBlock(kind="text", text=text),),
            structured_content=None,
        ),
    )
    return workflow


def ask(agent: AgentReadWorkflow, **changes: Any):
    values: dict[str, Any] = {"question": "Que dit KAN-1 ?", "correlation_id": "corr-agent-1"}
    values.update(changes)
    return asyncio.run(agent.answer(question=AgentQuestion(**values), context=CONTEXT))


def test_an_answer_without_tool_calls_ends_the_loop() -> None:
    provider = ScriptedProvider(answered("Jira suit les tickets."))
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    answer = ask(agent)

    assert answer.text == "Jira suit les tickets."
    assert answer.stop_reason == AgentStopReason.ANSWERED
    assert answer.steps_used == 1
    assert answer.reads == ()


def test_a_read_is_performed_and_its_result_returned_to_the_model() -> None:
    provider = ScriptedProvider(proposing(), answered("KAN-1 parle de connexion."))
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    answer = ask(agent)

    assert answer.stop_reason == AgentStopReason.ANSWERED
    assert answer.steps_used == 2
    second_turn = provider.requests[1].messages
    assert second_turn[-1]["role"] == "tool"
    assert second_turn[-1]["tool_call_id"] == "call_1"
    assert '"key": "KAN-1"' in second_turn[-1]["content"]


def test_the_provenance_of_each_read_is_carried_out_of_the_loop() -> None:
    provider = ScriptedProvider(proposing(), answered("Fait."))
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    answer = ask(agent)

    assert len(answer.reads) == 1
    # The citation layer will render this; it comes from the workflow, never from
    # the model's account of what it read.
    assert answer.reads[0].tool_name == "getJiraIssue"
    assert answer.reads[0].correlation_id == "corr-agent-1"


def test_the_assistant_turn_is_rebuilt_from_validated_fields() -> None:
    provider = ScriptedProvider(proposing(), answered("Fait."))
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    ask(agent)

    turn = provider.requests[1].messages[-2]
    assert turn["role"] == "assistant"
    assert turn["tool_calls"][0]["id"] == "call_1"
    assert json.loads(turn["tool_calls"][0]["function"]["arguments"]) == {"issueIdOrKey": "KAN-1"}


def test_the_step_limit_stops_a_model_that_keeps_calling_tools() -> None:
    provider = ScriptedProvider(*[proposing() for _ in range(3)])
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    answer = ask(agent, max_steps=3)

    assert answer.stop_reason == AgentStopReason.STEP_LIMIT_REACHED
    assert answer.steps_used == 3
    assert len(answer.reads) == 3


@pytest.mark.parametrize(
    "error",
    [MCPInputRejected(), MCPRemoteToolFailure(), MCPResponseTooLarge()],
)
def test_a_recoverable_read_failure_is_handed_back_to_the_model(error: Exception) -> None:
    provider = ScriptedProvider(proposing(), answered("Je n'ai pas pu lire ce ticket."))
    agent = AgentReadWorkflow(provider=provider, reads=RefusingReads(error))

    answer = ask(agent)

    assert answer.stop_reason == AgentStopReason.ANSWERED
    observation = provider.requests[1].messages[-1]["content"]
    assert error.code in observation
    # A failed read is not a source, so it must not appear as one.
    assert answer.reads == ()


@pytest.mark.parametrize(
    "error",
    [
        MCPProviderDisabled(),
        MCPToolDenied(),
        MCPGrantUnavailable(),
        MCPAuditUnavailable(),
        MCPDNSRejected(),
        MCPSchemaRejected(),
        MCPRateLimited(),
        MCPTransportFailure(),
    ],
)
def test_a_security_or_infrastructure_refusal_stops_the_loop(error: Exception) -> None:
    # Retrying against a closed door burns the token budget and hides the refusal
    # from the caller behind a vague answer.
    provider = ScriptedProvider(proposing(), answered("jamais atteint"))
    agent = AgentReadWorkflow(provider=provider, reads=RefusingReads(error))

    with pytest.raises(type(error)):
        ask(agent)

    assert len(provider.requests) == 1


def test_an_llm_failure_is_not_swallowed_by_the_loop() -> None:
    provider = ScriptedProvider(LLMRateLimited())
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    with pytest.raises(LLMRateLimited):
        ask(agent)


def test_the_action_class_is_imposed_not_carried_over() -> None:
    reads = RefusingReads(MCPRemoteToolFailure())
    provider = ScriptedProvider(proposing(), answered("Fait."))
    agent = AgentReadWorkflow(provider=provider, reads=reads)

    ask(agent)

    assert reads.calls[0].action_class == ToolActionClass.READ


def test_the_correlation_id_reaches_the_read() -> None:
    reads = RefusingReads(MCPRemoteToolFailure())
    provider = ScriptedProvider(proposing(), answered("Fait."))
    agent = AgentReadWorkflow(provider=provider, reads=reads)

    ask(agent, correlation_id="corr-xyz")

    assert reads.calls[0].correlation_id == "corr-xyz"


def test_the_tool_name_routes_to_its_own_source_system() -> None:
    reads = RefusingReads(MCPRemoteToolFailure())
    provider = ScriptedProvider(
        proposing("getConfluencePage", {"pageId": "12345"}),
        answered("Fait."),
    )
    agent = AgentReadWorkflow(provider=provider, reads=reads)

    ask(agent)

    assert reads.calls[0].source_system == SourceSystem.CONFLUENCE


def test_the_model_is_only_offered_names_the_registry_knows() -> None:
    provider = ScriptedProvider(answered("Fait."))
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    ask(agent)

    offered = {tool["function"]["name"] for tool in provider.requests[0].tools}
    assert offered == {contract.tool_name for contract in MCPToolRegistry().contracts}
    assert set(provider.requests[0].allowed_tool_names) == offered


def test_the_catalogue_exposes_public_schemas_not_provider_ones() -> None:
    registry = MCPToolRegistry()
    catalogue = {
        tool["function"]["name"]: tool["function"]["parameters"]
        for tool in tool_catalogue(registry)
    }

    for contract in registry.contracts:
        assert catalogue[contract.tool_name] == contract.public_input_schema


def test_no_binding_argument_is_ever_offered_to_the_model() -> None:
    # The bindings are injected server-side after the model has chosen. If one
    # appeared in the catalogue the model could select a tenant, which is the
    # single thing it must never be able to do.
    forbidden = {"cloudId", "cloud_id", "siteUrl", "accessToken"}

    for tool in tool_catalogue(MCPToolRegistry()):
        assert not forbidden & set(tool["function"]["parameters"].get("properties", {}))


def test_an_oversized_observation_is_truncated_and_says_so() -> None:
    provider = ScriptedProvider(proposing(), answered("Fait."))
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads("x" * 40_000))

    ask(agent)

    observation = provider.requests[1].messages[-1]["content"]
    assert len(observation) < 40_000
    assert "tronquee" in observation
    # A model that cannot tell it received a fragment answers as though it received
    # the whole thing.
    assert observation.startswith("x" * MAX_OBSERVATION_CHARACTERS)


def test_a_duplicate_tool_name_is_refused_at_construction() -> None:
    registry = MCPToolRegistry()
    contract = registry.contracts[2]
    from dataclasses import replace

    twin = replace(contract, source_system=SourceSystem.CONFLUENCE)

    with pytest.raises(ValueError, match="two source systems"):
        AgentReadWorkflow(
            provider=ScriptedProvider(),
            reads=jira_reads(),
            registry=MCPToolRegistry((contract, twin)),
        )


def test_the_system_prompt_frames_read_content_as_data() -> None:
    provider = ScriptedProvider(answered("Fait."))
    agent = AgentReadWorkflow(provider=provider, reads=jira_reads())

    ask(agent)

    system = provider.requests[0].messages[0]
    assert system["role"] == "system"
    assert "DONNEE" in system["content"]
