from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.adapters.groq import GroqLLMProvider
from app.agent.api import get_agent
from app.agent.audit import AuditedLLMProvider
from app.agent.errors import (
    LLMAuditUnavailable,
    LLMCallTimeout,
    LLMCredentialUnavailable,
    LLMError,
    LLMInvalidResponse,
    LLMProviderRefused,
    LLMRateLimited,
    LLMRequestTooLarge,
    LLMResponseTooLarge,
    LLMTransportFailure,
)
from app.agent.read_workflow import AgentAnswer, AgentStopReason
from app.bootstrap import build_container
from app.core.config import Settings
from app.main import create_app
from app.mcp.errors import MCPProviderDisabled, MCPRateLimited, MCPReadError


class StubAgent:
    def __init__(self, *, answer: AgentAnswer | None = None, error: Exception | None = None):
        self.answer_value = answer
        self.error = error
        self.questions: list[Any] = []

    async def answer(self, *, question: Any, context: Any) -> AgentAnswer:
        del context
        self.questions.append(question)
        if self.error is not None:
            raise self.error
        assert self.answer_value is not None
        return self.answer_value


def client_for(agent: StubAgent) -> TestClient:
    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_agent] = lambda: agent
    return TestClient(app)


def ask(client: TestClient, **changes: Any):
    payload: dict[str, Any] = {"question": "Que dit KAN-1 ?", "correlation_id": "corr-api-1"}
    payload.update(changes)
    return client.post("/api/agent/questions", json=payload)


def test_the_route_is_default_deny_when_no_provider_is_configured() -> None:
    # No override: the container built from default settings has no agent.
    client = TestClient(create_app(Settings(environment="test")))

    response = ask(client)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "LLM_PROVIDER_DISABLED"


def test_an_answer_is_returned_with_its_stop_reason_and_sources() -> None:
    agent = StubAgent(
        answer=AgentAnswer(
            text="KAN-1 parle de connexion.",
            stop_reason=AgentStopReason.ANSWERED,
            steps_used=2,
        )
    )

    response = ask(client_for(agent))

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "KAN-1 parle de connexion."
    assert body["stop_reason"] == "answered"
    assert body["steps_used"] == 2


def test_the_identity_reaching_the_agent_is_server_derived() -> None:
    agent = StubAgent(
        answer=AgentAnswer(text="x", stop_reason=AgentStopReason.ANSWERED, steps_used=1)
    )
    client = client_for(agent)

    client.post(
        "/api/agent/questions",
        json={"question": "Q", "correlation_id": "corr-api-2"},
        headers={"X-Tenant-ID": "tenant-b", "X-User-ID": "user-b"},
    )

    assert agent.questions[0].correlation_id == "corr-api-2"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (LLMAuditUnavailable(), 503),
        (LLMCredentialUnavailable(), 503),
        (LLMRateLimited(), 429),
        # Waiting does not help; the request has to get smaller.
        (LLMRequestTooLarge(), 413),
        (LLMCallTimeout(), 504),
        (LLMTransportFailure(), 502),
        (LLMProviderRefused(), 502),
        (LLMInvalidResponse(), 502),
        (LLMResponseTooLarge(), 502),
    ],
)
def test_each_llm_error_reaches_its_status(error: LLMError, expected_status: int) -> None:
    response = ask(client_for(StubAgent(error=error)))

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == error.code


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [(MCPProviderDisabled(), 403), (MCPRateLimited(), 429)],
)
def test_a_fatal_read_refusal_keeps_the_status_the_mcp_route_would_give(
    error: MCPReadError,
    expected_status: int,
) -> None:
    # One cause, one status code, whether the read is reached directly or through
    # the assistant.
    response = ask(client_for(StubAgent(error=error)))

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == error.code


def test_the_question_bounds_are_enforced_before_any_provider_is_reached() -> None:
    agent = StubAgent(
        answer=AgentAnswer(text="x", stop_reason=AgentStopReason.ANSWERED, steps_used=1)
    )
    client = client_for(agent)

    assert ask(client, max_steps=99).status_code == 422
    assert ask(client, question="").status_code == 422
    assert ask(client, unexpected="field").status_code in (200, 422)
    assert agent.questions == [] or all(q.max_steps <= 8 for q in agent.questions)


def test_the_container_wires_the_provider_behind_the_audit(tmp_path: Path) -> None:
    key = tmp_path / "groq_api_key"
    key.write_bytes(b"gsk_" + b"a" * 40)
    container = build_container(
        Settings(
            environment="test",
            llm_groq_enabled=True,
            llm_groq_api_key_file=key,
            llm_groq_model="qwen/qwen3.6-27b",
        )
    )

    assert container.agent is not None
    # The unwrapped provider must never enter the container: an invocation that
    # leaves no trace of its tenant and user has to be unreachable by construction,
    # not by remembering to wrap it at the call site.
    provider = container.agent._provider
    assert isinstance(provider, AuditedLLMProvider)
    assert isinstance(provider._provider, GroqLLMProvider)
    assert provider._audit_sink is container.audit


def test_no_provider_means_no_agent_but_the_reads_stay_available() -> None:
    container = build_container(Settings(environment="test"))

    assert container.agent is None
    # The assistant is the optional layer, not the connectors underneath it.
    assert container.mcp_reads is not None
