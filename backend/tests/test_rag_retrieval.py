"""Retrieval feeding the orchestration loop.

The property under test is not "does retrieval help" -- a stub model cannot show
that, and the measurement lives in data/evaluation. It is that retrieval changes
what the model is *shown* without changing what the system is willing to
*claim*: a lead is offered as a lead, it never becomes a citation on its own,
and an index that fails takes nothing down with it.
"""

import pytest

from app.agent.domain import LLMResponse
from app.agent.read_workflow import (
    RETRIEVAL_HEADER,
    AgentQuestion,
    AgentReadWorkflow,
)
from app.audit.domain import AuditEventType
from app.core.identity import SecurityContext
from app.semantics.domain import SimilarDocument

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RecordingProvider:
    """A model that answers immediately and remembers what it was shown."""

    def __init__(self, text: str = "Reponse.") -> None:
        self.text = text
        self.transcripts: list[tuple[dict, ...]] = []

    async def generate(self, *, request, context):
        self.transcripts.append(request.messages)
        return LLMResponse(text=self.text, tool_calls=(), model_name="stub-model")


class CollectingAudit:
    def __init__(self) -> None:
        self.events: list = []

    def append(self, event) -> None:
        self.events.append(event)


class StubIndex:
    """Stands in for SemanticIndex, including the ways it can fail."""

    def __init__(self, trouves=None, explode: bool = False) -> None:
        self._trouves = trouves or []
        self._explode = explode
        self.demandes: list[tuple[str, str, int]] = []

    def search(self, tenant_id, question, *, limit):
        self.demandes.append((tenant_id, question, limit))
        if self._explode:
            raise RuntimeError("the model would not load")
        return self._trouves


def piste(external_id: str, distance: float = 0.12) -> SimilarDocument:
    return SimilarDocument(
        external_id=external_id,
        title=f"Titre de {external_id}",
        resource_reference=f"https://exemple.invalid/browse/{external_id}",
        source_system="jira",
        distance=distance,
    )


class RefusingReads:
    """No read should be needed by these tests; calling one is the failure."""

    async def execute_call(self, *, call, context):  # pragma: no cover - guard
        raise AssertionError("no read was expected in this test")


def workflow_for(index=None, audit=None, provider=None) -> AgentReadWorkflow:
    return AgentReadWorkflow(
        provider=provider or RecordingProvider(),
        reads=RefusingReads(),
        audit_sink=audit or CollectingAudit(),
        semantic_index=index,
    )


def question() -> AgentQuestion:
    return AgentQuestion(question="le mail de confirmation n'arrive pas", correlation_id="c-1")


def context() -> SecurityContext:
    return SecurityContext(tenant_id="locataire-a", user_id="fanny")


async def test_the_leads_reach_the_model_labelled_as_leads() -> None:
    """Framing is the control here, not decoration.

    The system prompt already states that a search result is a starting point
    and not a source. If the shortlist arrived unlabelled, the model would have
    no way to tell an index hit from something it had actually read, and the
    project's rule about citations would rest on nothing.
    """

    provider = RecordingProvider()
    index = StubIndex([piste("KAN-2"), piste("KAN-3", 0.20)])

    await workflow_for(index=index, provider=provider).answer(
        question=question(), context=context()
    )

    transcript = provider.transcripts[0]
    injecte = next(m for m in transcript if m["content"].startswith(RETRIEVAL_HEADER))
    assert "PISTES" in injecte["content"]
    assert "KAN-2" in injecte["content"] and "KAN-3" in injecte["content"]
    # A system turn, not a user turn: the shortlist is not something the person
    # asked, and dressing it as their words would let index content read as intent.
    assert injecte["role"] == "system"


async def test_a_lead_never_becomes_a_citation_on_its_own() -> None:
    """The invariant the whole slice hangs on.

    Citations are the provenance of reads actually performed. Letting the index
    write one would cite a document that was never opened during this exchange --
    exactly the fabricated citation the read pipeline exists to prevent.
    """

    index = StubIndex([piste("KAN-2"), piste("KAN-3")])

    answer = await workflow_for(index=index).answer(question=question(), context=context())

    assert answer.sources == ()


async def test_retrieval_is_scoped_to_the_caller_s_tenant() -> None:
    index = StubIndex([piste("KAN-2")])

    await workflow_for(index=index).answer(question=question(), context=context())

    tenant, _, _ = index.demandes[0]
    assert tenant == "locataire-a"


async def test_an_index_that_fails_does_not_take_the_question_down() -> None:
    """Retrieval improves an answer; it is not what makes one correct.

    An empty, unreachable, or unloadable index must degrade to the behaviour
    that existed before retrieval -- reads without leads. The reverse would turn
    a quality feature into a dependency of availability.
    """

    provider = RecordingProvider("Reponse malgre tout.")
    index = StubIndex(explode=True)

    answer = await workflow_for(index=index, provider=provider).answer(
        question=question(), context=context()
    )

    assert answer.text == "Reponse malgre tout."
    assert not any(m["content"].startswith(RETRIEVAL_HEADER) for m in provider.transcripts[0])


async def test_an_empty_index_adds_nothing_to_the_transcript() -> None:
    # Not an empty heading with no leads under it: a header promising a
    # shortlist and delivering none invites the model to invent its own.
    provider = RecordingProvider()

    await workflow_for(index=StubIndex([]), provider=provider).answer(
        question=question(), context=context()
    )

    assert not any(m["content"].startswith(RETRIEVAL_HEADER) for m in provider.transcripts[0])


async def test_no_index_at_all_behaves_exactly_as_before() -> None:
    provider = RecordingProvider()

    answer = await workflow_for(index=None, provider=provider).answer(
        question=question(), context=context()
    )

    assert answer.text == "Reponse."
    assert len(provider.transcripts[0]) == 2


async def test_the_shortlist_is_recorded_without_its_contents() -> None:
    """The trail says what was offered, not what it contained.

    Recorded at all because it shapes the answer: one question answered with
    leads and the same one answered without are two different runs, and a trail
    that cannot tell them apart cannot explain why one cited a ticket the other
    never mentioned.
    """

    audit = CollectingAudit()
    index = StubIndex([piste("KAN-2", 0.1234567)])

    await workflow_for(index=index, audit=audit).answer(question=question(), context=context())

    evenement = next(
        event
        for event in audit.events
        if event.event_type == AuditEventType.SEMANTIC_RETRIEVAL_COMPLETED
    )
    assert evenement.tenant_id == "locataire-a"
    assert evenement.correlation_id == "c-1"
    assert evenement.details["leads"] == [{"external_id": "KAN-2", "distance": 0.1235}]
    assert "Titre de KAN-2" not in str(evenement.details)


async def test_an_unwritable_audit_entry_does_not_refuse_the_question() -> None:
    """Unlike a read, no source was consulted, so the access trail has no gap."""

    class BrokenAudit:
        def append(self, event) -> None:
            raise RuntimeError("sink down")

    answer = await workflow_for(index=StubIndex([piste("KAN-2")]), audit=BrokenAudit()).answer(
        question=question(), context=context()
    )

    assert answer.text == "Reponse."


async def test_the_lead_count_is_the_deployment_s_choice_not_the_question_s() -> None:
    index = StubIndex([piste("KAN-2")])
    workflow = AgentReadWorkflow(
        provider=RecordingProvider(),
        reads=RefusingReads(),
        audit_sink=CollectingAudit(),
        semantic_index=index,
        retrieval_limit=3,
    )

    await workflow.answer(question=question(), context=context())

    _, _, limit = index.demandes[0]
    assert limit == 3
