from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agent.api import get_agent
from app.agent.citations import AgentSource
from app.agent.errors import LLMRateLimited
from app.agent.read_workflow import AgentAnswer, AgentStopReason
from app.core.config import Settings
from app.main import create_app
from app.mcp.domain import MCPReadSourceSystem

OWNER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "owner"}
OTHER_USER = {"X-Tenant-ID": "tenant-a", "X-User-ID": "someone-else"}
OTHER_TENANT = {"X-Tenant-ID": "tenant-b", "X-User-ID": "owner"}

CITED = AgentSource(
    source_system=MCPReadSourceSystem.JIRA,
    tool_name="getJiraIssue",
    url="https://example.invalid/browse/KAN-1",
    retrieved_at=datetime(2026, 8, 18, 4, 26, tzinfo=UTC),
)
ENUMERATED = AgentSource(
    source_system=MCPReadSourceSystem.JIRA,
    tool_name="searchJiraIssuesUsingJql",
    url=None,
    retrieved_at=datetime(2026, 8, 18, 4, 25, tzinfo=UTC),
    truncated=True,
)


class StubAgent:
    """Records what it was asked, so a test can prove it was never called."""

    def __init__(self, *, answer: AgentAnswer | None = None, error: Exception | None = None):
        self.answer_value = answer
        self.error = error
        self.questions: list[Any] = []
        # L'historique tel que la route l'a reellement transmis. Capture plutot
        # qu'ignore : c'est la seule facon de prouver ce que le modele a revu.
        self.histories: list[tuple[Any, ...]] = []

    async def answer(self, *, question: Any, context: Any, history: Any = ()) -> AgentAnswer:
        del context
        self.questions.append(question)
        self.histories.append(tuple(history))
        if self.error is not None:
            raise self.error
        assert self.answer_value is not None
        return self.answer_value


def an_answer(*sources: AgentSource) -> AgentAnswer:
    return AgentAnswer(
        text="KAN-1 porte le resume test et le statut A faire.",
        stop_reason=AgentStopReason.ANSWERED,
        steps_used=2,
        sources=sources,
    )


def client_for(agent: StubAgent | None = None) -> TestClient:
    app = create_app(Settings(environment="test"))
    if agent is not None:
        app.dependency_overrides[get_agent] = lambda: agent
    return TestClient(app)


def a_conversation(client: TestClient, headers: dict[str, str] = OWNER) -> str:
    created = client.post("/api/conversations", headers=headers, json={"title": "Suivi KAN"})
    assert created.status_code == 201
    return created.json()["id"]


def ask(client: TestClient, **changes: Any):
    payload: dict[str, Any] = {
        "question": "Que dit KAN-1 ?",
        "correlation_id": "corr-history-1",
    }
    payload.update(changes)
    return client.post("/api/agent/questions", headers=OWNER, json=payload)


def test_both_turns_survive_a_reload() -> None:
    # The point of the whole slice: a conversation reread from storage is the
    # conversation that happened, not an empty thread.
    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)

    assert ask(client, conversation_id=conversation).status_code == 200

    history = client.get(f"/api/conversations/{conversation}/messages", headers=OWNER)
    assert history.status_code == 200
    turns = history.json()
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "Que dit KAN-1 ?"
    assert turns[1]["content"].startswith("KAN-1 porte")
    # One exchange, one correlation id: this is what ties a displayed answer to the
    # reads that produced it in the audit trail.
    assert {turn["correlation_id"] for turn in turns} == {"corr-history-1"}


def test_a_stored_citation_carries_no_score_and_no_inferred_flag() -> None:
    # The decision taken at the API is enforced again by the schema, which has no
    # column for either. A restyled front end cannot resurrect them from storage.
    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)
    ask(client, conversation_id=conversation)

    turns = client.get(f"/api/conversations/{conversation}/messages", headers=OWNER).json()
    source = turns[1]["sources"][0]

    assert source["resource_reference"] == "https://example.invalid/browse/KAN-1"
    assert "confidence" not in source
    assert "inferred" not in source


def test_sources_keep_the_order_they_were_consulted_in() -> None:
    # Stored rather than recomputed: a citation list whose order moved between two
    # readings of the same answer would look like the answer changed.
    agent = StubAgent(answer=an_answer(ENUMERATED, CITED))
    client = client_for(agent)
    conversation = a_conversation(client)
    ask(client, conversation_id=conversation)

    sources = client.get(
        f"/api/conversations/{conversation}/messages", headers=OWNER
    ).json()[1]["sources"]

    assert [source["tool_name"] for source in sources] == [
        "searchJiraIssuesUsingJql",
        "getJiraIssue",
    ]
    # A read that enumerates rather than designates has no link to offer, and the
    # truncation flag is the one thing a reader cannot infer from the link.
    assert sources[0]["resource_reference"] is None
    assert sources[0]["truncated"] is True


def test_history_is_invisible_to_another_user_and_to_another_tenant() -> None:
    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)
    ask(client, conversation_id=conversation)

    for headers in (OTHER_USER, OTHER_TENANT):
        response = client.get(f"/api/conversations/{conversation}/messages", headers=headers)
        # 404 and not 403: a conversation belonging to someone else must not be
        # distinguishable from one that does not exist.
        assert response.status_code == 404


def test_an_unknown_conversation_refuses_before_the_model_is_called() -> None:
    # Spending a real call to then discover the thread is not the caller's would
    # waste a budget for an answer nobody can be given.
    agent = StubAgent(answer=an_answer())
    client = client_for(agent)

    response = ask(client, conversation_id=str(uuid4()))

    assert response.status_code == 404
    assert agent.questions == []


def test_someone_elses_conversation_is_refused_before_the_model_is_called() -> None:
    agent = StubAgent(answer=an_answer())
    client = client_for(agent)
    conversation = a_conversation(client, headers=OTHER_USER)

    response = ask(client, conversation_id=conversation)

    assert response.status_code == 404
    assert agent.questions == []


def test_an_exchange_without_a_conversation_still_answers_and_stores_nothing() -> None:
    # The field is optional so the front end keeps working the day this ships,
    # before it has been taught to send a thread.
    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)

    assert ask(client).status_code == 200

    assert client.get(f"/api/conversations/{conversation}/messages", headers=OWNER).json() == []


def test_the_question_survives_a_provider_refusal() -> None:
    # The user turn is written before the call, so a 429 leaves a question with no
    # answer beside it -- which is exactly what happened.
    agent = StubAgent(error=LLMRateLimited())
    client = client_for(agent)
    conversation = a_conversation(client)

    assert ask(client, conversation_id=conversation).status_code == 429

    turns = client.get(f"/api/conversations/{conversation}/messages", headers=OWNER).json()
    assert [turn["role"] for turn in turns] == ["user"]


def test_a_history_failure_does_not_discard_the_answer() -> None:
    # Unlike the audit trail, history is not fail-closed: refusing an answer already
    # paid for, because a row could not be written, destroys more than it protects.
    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)

    workflow = client.app.state.container.conversations

    def refuse(message: Any) -> None:
        raise RuntimeError("storage unavailable")

    workflow._messages.append = refuse  # type: ignore[method-assign]

    response = ask(client, conversation_id=conversation)

    assert response.status_code == 200
    assert response.json()["text"].startswith("KAN-1 porte")


def test_the_returned_history_is_capped_server_side() -> None:
    client = client_for()
    conversation = a_conversation(client)

    over = client.get(
        f"/api/conversations/{conversation}/messages",
        headers=OWNER,
        params={"limit": 5_000},
    )

    # Refused by the schema rather than silently reduced: a caller that asked for
    # more than the server will ever give should be told, not quietly served less.
    assert over.status_code == 422


def test_the_order_does_not_depend_on_the_clock() -> None:
    # Regression guard. Both turns of one exchange are written inside a single clock
    # tick on Windows, where the resolution is around 15 ms: ordering on created_at
    # made the tie fall to a random uuid, and the thread displayed backwards roughly
    # half the time. Four turns written back to back would be shuffled; ranked by an
    # explicit sequence they cannot be.
    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)

    ask(client, conversation_id=conversation, correlation_id="corr-1")
    ask(client, conversation_id=conversation, correlation_id="corr-2")

    turns = client.get(f"/api/conversations/{conversation}/messages", headers=OWNER).json()

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]
    assert [turn["correlation_id"] for turn in turns] == [
        "corr-1",
        "corr-1",
        "corr-2",
        "corr-2",
    ]
    assert [turn["sequence"] for turn in turns] == [0, 1, 2, 3]


def test_the_second_question_sees_the_first_exchange() -> None:
    """Le defaut que cette tranche corrige, vu depuis la route.

    Les tours etaient ecrits et jamais relus : demander l'etat d'un ticket apres en
    avoir demande le contenu faisait redemander de quel ticket on parlait.
    """

    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)

    assert ask(client, conversation_id=conversation).status_code == 200
    assert ask(
        client,
        conversation_id=conversation,
        question="Et son statut ?",
        correlation_id="corr-history-2",
    ).status_code == 200

    premiere, seconde = agent.histories
    # La premiere question n'avait rien a revoir.
    assert premiere == ()
    assert [(t.role, t.content) for t in seconde] == [
        ("user", "Que dit KAN-1 ?"),
        ("assistant", "KAN-1 porte le resume test et le statut A faire."),
    ]


def test_the_current_question_is_not_replayed_to_itself() -> None:
    """L'ordre lecture-puis-ecriture, prouve plutot que commente.

    La route enregistre la question avant d'appeler le modele, pour qu'elle survive a
    un refus du fournisseur. Relire l'historique apres cette ecriture ferait arriver
    la question deux fois -- une fois comme souvenir, une fois comme question. Le bug
    serait silencieux : le modele repondrait quand meme, en croyant qu'on se repete.
    """

    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)
    conversation = a_conversation(client)

    assert ask(client, conversation_id=conversation).status_code == 200

    (historique,) = agent.histories
    assert "Que dit KAN-1 ?" not in [t.content for t in historique]


def test_an_exchange_without_a_conversation_replays_nothing() -> None:
    """Sans fil, rien a revoir -- et surtout aucune fuite d'un fil vers un autre."""

    agent = StubAgent(answer=an_answer(CITED))
    client = client_for(agent)

    assert ask(client).status_code == 200

    assert agent.histories == [()]
