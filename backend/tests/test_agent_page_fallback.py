"""La page proposee meme quand le modele oublie de la proposer.

Mesure a l'origine de ce rattrapage : une fois sur trois, le modele rendait le
tableau dans sa reponse et s'arretait la, sans appeler createConfluencePage. Ni la
fermete de la consigne ni le budget d'etapes n'y changeaient rien -- mesure a quatre
etapes comme a huit, le meme deux sur trois.

Le commentaire du registre le dit deja pour les lectures repetees : "un prompt ne peut
pas rendre un comportement impossible". La proposition est donc construite en code,
et c'est ce que ces tests verifient -- y compris, et surtout, ce qui l'en empeche.

Rien n'est ecrit pour autant : le rattrapage passe par le meme atelier d'approbation
que si le modele avait appele l'outil lui-meme.
"""

import asyncio
from typing import Any
from uuid import uuid4

from app.agent.read_workflow import (
    CONFLUENCE_CREATE_TOOL,
    AgentQuestion,
    AgentStopReason,
    _is_specification_table,
    _specification_title,
)
from app.approvals.workflow import ApprovalWorkflow
from app.conversations.adapters.memory import InMemoryConversationRepository
from app.conversations.domain import Conversation
from app.core.identity import SecurityContext
from app.figma.catalogue import FigmaFrameCatalogue
from app.mcp.mutation_registry import MCPMutationRegistry
from tests.test_agent_backlog_format import DEMANDE, process_reads, reading_process
from tests.test_agent_proposes_writes import (
    InMemoryApprovalUnitOfWork,
    RegistryMutationToolPin,
)
from tests.test_agent_read_workflow import ScriptedProvider, agent_for, answered

# Une ecriture exige une session et un fil : la proposition doit pouvoir etre
# rattachee a une conversation dont cette personne est proprietaire.
TENANT = "tenant-a"
USER = "user-a"
CONTEXT = SecurityContext(tenant_id=TENANT, user_id=USER, session_id=uuid4())


def agent_with_space(provider: Any, espace: str, *, with_desk: bool = True):
    reads = process_reads()
    conversations = InMemoryConversationRepository()
    uow = InMemoryApprovalUnitOfWork()
    approvals = ApprovalWorkflow(
        uow, conversations, RegistryMutationToolPin(), 900, "session"
    )
    fil = Conversation(tenant_id=TENANT, owner_user_id=USER, title="Fil")
    conversations.add(fil)
    agent = agent_for(
        provider,
        reads,
        audit_sink=uow.audit,
        frames=FigmaFrameCatalogue(reads=reads, file_keys=("UVQmgXGaZC5vrtaQRU5nvo",)),
        default_confluence_space=espace,
        mutations=MCPMutationRegistry() if with_desk else None,
        approvals=approvals if with_desk else None,
    )
    return agent, fil.id


def ask(agent_and_fil, question: str):
    agent, fil = agent_and_fil
    return asyncio.run(
        agent.answer(
            question=AgentQuestion(
                question=question, correlation_id="corr-1", conversation_id=fil
            ),
            context=CONTEXT,
        )
    )

TABLEAU = "\n".join(
    [
        "| Bloc fonctionnel | Ref. PBS | Userstory | Description | Criteres "
        "d'acceptation - Contexte | Criteres d'acceptation - Scenario | Remarques |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        "| Authentification | | En tant qu'utilisateur, je souhaite m'authentifier. "
        "| Ouvre l'application. | Etant donne que l'ecran est affiche | Lorsque "
        "l'utilisateur valide Alors l'accueil s'affiche | |",
    ]
)


def oublie_la_page(espace: str = "DL", **changes: Any):
    """Un modele qui lit le processus, rend le tableau, et n'appelle rien d'autre."""

    provider = ScriptedProvider(reading_process(), answered(TABLEAU))
    return agent_with_space(provider, espace, **changes)


# --- Ce qui fait un tableau, et ce qui n'en fait pas --------------------------------


def test_the_table_is_recognised_by_its_header() -> None:
    assert _is_specification_table(TABLEAU)


def test_prose_about_the_table_is_not_the_table() -> None:
    """Une reponse qui explique pourquoi le tableau n'a pas pu etre produit
    deviendrait sinon le corps d'une page, et l'humain approuverait un document qui
    parle du cahier des charges au lieu de le contenir."""

    assert not _is_specification_table(
        "Je n'ai pas pu produire le tableau : la maquette est introuvable."
    )


def test_another_table_is_not_the_specification() -> None:
    """Un tableau markdown quelconque -- une liste de tickets, par exemple -- ne doit
    pas devenir un cahier des charges."""

    assert not _is_specification_table("| Cle | Statut |\n| --- | --- |\n| KAN-1 | A faire |")


def test_the_title_names_the_maquette_when_it_is_known() -> None:
    """Une page nommee "Cahier des charges" parmi vingt autres ne se retrouve pas."""

    assert _specification_title("KIOSQUE K20") == "Cahier des charges - KIOSQUE K20"


def test_the_title_stays_generic_rather_than_invented() -> None:
    """Mieux vaut une page a renommer qu'un titre qui designerait une maquette dont
    on n'est pas sur."""

    assert _specification_title(None) == "Cahier des charges"


# --- Le rattrapage lui-meme ---------------------------------------------------------


def test_a_forgotten_page_is_proposed_all_the_same() -> None:
    agent = oublie_la_page()

    answer = ask(agent, question=DEMANDE)

    assert answer.stop_reason is AgentStopReason.APPROVAL_REQUIRED
    assert answer.approval is not None
    assert answer.approval.tool_name == CONFLUENCE_CREATE_TOOL
    assert answer.approval.payload["spaceId"] == "DL"
    assert answer.approval.payload["body"] == TABLEAU


def test_the_proposed_body_is_the_table_and_nothing_else() -> None:
    """Un corps qui annonce le cahier des charges sans le contenir fait approuver une
    page vide -- c'est le defaut que tout ce chemin existe pour eviter."""

    agent = oublie_la_page()

    answer = ask(agent, question=DEMANDE)

    assert answer.approval is not None
    assert answer.approval.payload["body"].startswith("| Bloc fonctionnel |")


def test_no_page_is_invented_without_a_configured_space() -> None:
    """Aucun espace ne peut etre devine, et en inventer un ferait approuver une page
    creee au mauvais endroit."""

    agent = oublie_la_page(espace="")

    answer = ask(agent, question=DEMANDE)

    assert answer.stop_reason is AgentStopReason.ANSWERED
    assert answer.approval is None


def test_no_page_without_an_approval_desk() -> None:
    """Sans atelier d'approbation, la proposition n'aurait personne pour la recevoir."""

    agent = oublie_la_page(with_desk=False)

    answer = ask(agent, question=DEMANDE)

    assert answer.stop_reason is AgentStopReason.ANSWERED
    assert answer.approval is None


def test_no_page_for_a_question_that_asked_for_none() -> None:
    """Le rattrapage suit la demande de la personne, jamais la forme du texte seul."""

    provider = ScriptedProvider(reading_process(), answered(TABLEAU))
    agent = agent_with_space(provider, "DL")

    answer = ask(agent, question="Resume-moi ce processus.")

    assert answer.stop_reason is AgentStopReason.ANSWERED
    assert answer.approval is None


def test_an_answer_in_prose_is_left_as_an_answer() -> None:
    provider = ScriptedProvider(
        reading_process(),
        answered("Je n'ai pas pu lire la maquette demandee."),
    )
    agent = agent_with_space(provider, "DL")

    answer = ask(agent, question=DEMANDE)

    assert answer.stop_reason is AgentStopReason.ANSWERED
    assert answer.approval is None
    assert "pas pu lire" in answer.text


def test_the_model_calling_the_tool_itself_still_wins() -> None:
    """Le rattrapage ne doit pas doubler une proposition deja faite."""

    from app.agent.domain import LLMResponse, ProposedToolCall
    from app.mcp.domain import ToolActionClass

    appel = LLMResponse(
        text="",
        model_name="stub",
        tool_calls=(
            ProposedToolCall(
                call_id="c1",
                tool_name=CONFLUENCE_CREATE_TOOL,
                action_class=ToolActionClass.CREATE,
                arguments={"spaceId": "DL", "title": "Ecrit par le modele", "body": TABLEAU},
            ),
        ),
    )
    provider = ScriptedProvider(reading_process(), appel)
    agent = agent_with_space(provider, "DL")

    answer = ask(agent, question=DEMANDE)

    assert answer.approval is not None
    assert answer.approval.payload["title"] == "Ecrit par le modele"
