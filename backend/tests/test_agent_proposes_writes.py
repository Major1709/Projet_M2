"""Le maillon manquant : le modele demande une ecriture, la boucle s'arrete.

Avant cette tranche, NEXIA savait executer une ecriture approuvee mais ne pouvait pas
en proposer une : le catalogue ne contenait que des lectures, et rien ne transformait
un appel d'outil en ActionProposal. La chaine fonctionnait si on lui donnait une
proposition a la main, jamais depuis une question en langage naturel.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agent.domain import LLMResponse, ProposedToolCall
from app.agent.read_workflow import (
    NO_CONVERSATION_MESSAGE,
    PROPOSAL_MESSAGE,
    AgentQuestion,
    AgentReadWorkflow,
    AgentStopReason,
)
from app.approvals.adapters.memory import InMemoryApprovalUnitOfWork
from app.approvals.adapters.tool_pin import RegistryMutationToolPin
from app.approvals.workflow import ApprovalWorkflow
from app.conversations.adapters.memory import InMemoryConversationRepository
from app.conversations.domain import Conversation
from app.core.identity import SecurityContext
from app.mcp.domain import ToolActionClass
from app.mcp.mutation_registry import MCPMutationRegistry

TENANT = "tenant-a"
USER = "user-a"
CONTEXT = SecurityContext(tenant_id=TENANT, user_id=USER, session_id=uuid4())
PAYLOAD = {"projectKey": "KAN", "issueTypeName": "Bug", "summary": "Le courriel ne part pas"}


class StubProvider:
    """Rend les reponses qu'on lui a donnees, dans l'ordre."""

    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    @property
    def model_name(self) -> str:
        return "stub"

    async def generate(self, *, request, context):
        self.requests.append(request)
        return self._responses.pop(0)


class StubReads:
    async def execute_call(self, *, call, context):  # pragma: no cover - jamais atteint
        raise AssertionError("une ecriture ne doit jamais passer par le chemin de lecture")


def a_call(name: str = "createJiraIssue", arguments: dict | None = None) -> ProposedToolCall:
    return ProposedToolCall(
        call_id="call_1",
        tool_name=name,
        action_class=ToolActionClass.READ,
        arguments=PAYLOAD if arguments is None else arguments,
    )


def a_response(*calls: ProposedToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(text=text, tool_calls=calls, model_name="stub")


def workflow_for(provider: StubProvider, *, with_writes: bool = True):
    conversations = InMemoryConversationRepository()
    uow = InMemoryApprovalUnitOfWork()
    approvals = ApprovalWorkflow(
        uow, conversations, RegistryMutationToolPin(), 900, "session"
    )
    workflow = AgentReadWorkflow(
        provider=provider,
        reads=StubReads(),
        audit_sink=uow.audit,
        mutations=MCPMutationRegistry() if with_writes else None,
        approvals=approvals if with_writes else None,
    )
    return workflow, conversations


def a_conversation(repository: InMemoryConversationRepository) -> UUID:
    conversation = Conversation(tenant_id=TENANT, owner_user_id=USER, title="Fil")
    repository.add(conversation)
    return conversation.id


def a_question(conversation_id: UUID | None) -> AgentQuestion:
    return AgentQuestion(
        question="cree un ticket pour le bug du courriel",
        correlation_id="corr-1",
        conversation_id=conversation_id,
    )


@pytest.mark.anyio
async def test_a_write_becomes_a_proposal_and_stops_the_loop() -> None:
    """Le maillon lui-meme. Rien n'est ecrit : une question est posee a un humain."""

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )

    assert answer.stop_reason is AgentStopReason.APPROVAL_REQUIRED
    assert answer.text == PROPOSAL_MESSAGE
    assert answer.approval is not None
    assert answer.approval.tool_name == "createJiraIssue"
    assert answer.approval.payload == PAYLOAD
    # Un seul appel au modele : la boucle s'arrete, elle ne redemande pas.
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_the_decision_token_comes_back_with_the_proposal() -> None:
    """Il n'est rendu qu'ici. Un client qui ne le garde pas ne pourra plus approuver,
    et un rechargement de page ne permet pas de le recuperer."""

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )

    assert answer.approval is not None
    assert len(answer.approval.decision_token) > 20


@pytest.mark.anyio
async def test_the_action_class_comes_from_the_contract_and_not_from_the_model() -> None:
    """La propriete qui compte le plus ici.

    Le double envoie deliberement action_class=READ sur un outil de creation. Si la
    classe venait du modele, une suppression pourrait s'afficher comme une creation
    dans l'ecran d'approbation -- l'humain approuverait autre chose que ce qui
    partirait.
    """

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )

    assert answer.approval is not None
    assert answer.approval.action_class is ToolActionClass.CREATE


@pytest.mark.anyio
async def test_only_the_first_write_of_a_turn_survives() -> None:
    """Chaque ecriture doit etre vue et approuvee separement. Continuer laisserait le
    modele enchainer plusieurs ecritures sur une seule question."""

    provider = StubProvider(
        a_response(
            a_call(arguments={**PAYLOAD, "summary": "premier"}),
            a_call(arguments={**PAYLOAD, "summary": "second"}),
        )
    )
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )

    assert answer.approval is not None
    assert answer.approval.payload["summary"] == "premier"


@pytest.mark.anyio
async def test_a_write_outside_a_conversation_is_refused_not_invented() -> None:
    """Une proposition appartient a un fil : c'est ce qui permet d'en verifier le
    proprietaire et de l'afficher au bon endroit."""

    provider = StubProvider(a_response(a_call()))
    workflow, _ = workflow_for(provider)

    answer = await workflow.answer(question=a_question(None), context=CONTEXT)

    assert answer.approval is None
    assert answer.text == NO_CONVERSATION_MESSAGE
    assert answer.stop_reason is AgentStopReason.ANSWERED


@pytest.mark.anyio
async def test_a_write_never_reaches_the_read_path() -> None:
    """``StubReads`` leve si on l'appelle : ce test echouerait bruyamment si une
    ecriture etait routee comme une lecture."""

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )

    assert answer.stop_reason is AgentStopReason.APPROVAL_REQUIRED


@pytest.mark.anyio
async def test_a_deployment_without_writes_offers_none_and_ignores_the_name() -> None:
    """Sans atelier d'approbation, l'outil n'est pas offert -- et un modele qui le
    nommerait quand meme retombe sur le chemin ordinaire, ou le registre de lecture
    le refuse comme un nom inconnu."""

    provider = StubProvider(a_response(a_call()), a_response(text="je ne sais pas faire"))
    workflow, repository = workflow_for(provider, with_writes=False)

    offerts = {c["function"]["name"] for c in workflow._catalogue}

    assert "createJiraIssue" not in offerts


def test_a_registry_without_a_workflow_is_a_wiring_error() -> None:
    """Les deux vont ensemble : un registre seul offrirait des outils que personne ne
    peut transformer en proposition."""

    with pytest.raises(ValueError, match="go together"):
        AgentReadWorkflow(
            provider=StubProvider(),
            reads=StubReads(),
            audit_sink=InMemoryApprovalUnitOfWork().audit,
            mutations=MCPMutationRegistry(),
            approvals=None,
        )


@pytest.mark.anyio
async def test_the_write_tool_is_named_in_the_catalogue_the_model_receives() -> None:
    """Et il entre dans les noms autorises : sans cela l'adaptateur journalise "outil
    non offert" a chaque proposition, en disant au modele qu'il a invente un nom qu'on
    venait pourtant de lui montrer."""

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    await workflow.answer(question=a_question(a_conversation(repository)), context=CONTEXT)

    request = provider.requests[0]
    assert "createJiraIssue" in {t["function"]["name"] for t in request.tools}
    assert "createJiraIssue" in request.allowed_tool_names


# --- Le contrat de fil, tel que le frontend le lit ---------------------------------
#
# Les deux cotes ont ete ecrits en parallele et avaient choisi des noms differents :
# le backend envoyait "proposal", le frontend lisait "approval". Rien ne cassait --
# parseApproval recevait undefined et rendait undefined -- et l'ecran d'approbation
# restait simplement vide. Un desaccord silencieux, trouve en essayant l'interface.
#
# Ces tests figent les noms que ``parseApproval`` lit reellement, pour qu'un
# renommage futur echoue ici plutot que dans l'interface.


@pytest.mark.anyio
async def test_the_wire_field_is_named_approval() -> None:
    """Le nom que le frontend lit. Nomme "proposal", il redevient invisible."""

    import json

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )
    envoye = json.loads(answer.model_dump_json())

    assert "approval" in envoye
    assert "proposal" not in envoye


@pytest.mark.anyio
async def test_every_field_the_front_end_reads_is_present() -> None:
    """Releve dans ``parseApproval`` le 07/09/2026. Un champ absent ne casse rien
    visiblement : il disparait simplement de l'ecran, ce qui est pire."""

    import json

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )
    approval = json.loads(answer.model_dump_json())["approval"]

    for champ in (
        "id",
        "decision_token",
        "version",
        "state",
        "action_class",
        "tool_name",
        "payload",
        "explanation",
        "expires_at",
        "source_system",
    ):
        assert champ in approval, champ


@pytest.mark.anyio
async def test_the_payload_carries_what_the_approval_screen_displays() -> None:
    """Le projet et le titre sont ce qui dit a l'humain OU l'ecriture atterrira."""

    import json

    provider = StubProvider(a_response(a_call()))
    workflow, repository = workflow_for(provider)

    answer = await workflow.answer(
        question=a_question(a_conversation(repository)), context=CONTEXT
    )
    payload = json.loads(answer.model_dump_json())["approval"]["payload"]

    assert payload["projectKey"] == "KAN"
    assert payload["summary"] == "Le courriel ne part pas"
