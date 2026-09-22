"""Croiser Jira et Confluence sur une question large, sans qu'on le demande.

Mesure a l'origine de ce rappel : sur trois questions posees sans nommer d'outil --
"fais-moi le point sur le projet KAN", "ou en est le projet KAN", "resume-moi tout ce
qu'on sait" -- le modele croisait deux fois sur trois. La troisieme, il s'arretait a
Jira, et sa reponse paraissait complete alors qu'elle etait partielle. Rien ne lui
disait qu'un projet vit dans plusieurs sources.

Le declencheur est un COMPORTEMENT, pas un mot devine dans la question : le registre
sait deja qu'un contrat sans ``resource_reference_path`` ne designe aucune ressource.
Chercher, c'est explorer un sujet ; lire un ticket par sa cle, c'est repondre a une
question etroite qui n'a rien a gagner a ouvrir Confluence.

Cette distinction est ce que les tests ci-dessous protegent : un rappel qui se
declencherait sur "que contient KAN-1 ?" ferait depenser des lectures pour rien, et
allongerait une reponse qui allait bien.
"""

from typing import Any

from app.agent.read_workflow import (
    CROSS_SOURCE_TURN,
    AgentReadWorkflow,
    _is_exploration,
)
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.ports import RemoteContentBlock, RemoteToolResult
from app.mcp.registry import MCPToolRegistry
from tests.test_agent_read_workflow import (
    ScriptedProvider,
    agent_for,
    answered,
    ask,
    proposing,
)
from tests.test_mcp_read_workflow import workflow_for

LARGE = "Fais-moi le point sur le projet KAN."


def reads_of(source: SourceSystem, tool: str, text: str = '{"issues": []}'):
    workflow, _, _ = workflow_for(
        source,
        tool,
        result=RemoteToolResult(
            content=(RemoteContentBlock(kind="text", text=text),),
            structured_content=None,
        ),
    )
    return workflow


def searching_jira(jql: str = "project = KAN", **changes: Any):
    return proposing("searchJiraIssuesUsingJql", {"jql": jql}, **changes)


def rappels(provider: ScriptedProvider) -> list[str]:
    return [
        str(m["content"])
        for m in provider.requests[-1].messages
        if m["role"] == "system" and "Tu viens de chercher" in str(m["content"])
    ]


# --- Ce qui distingue une exploration d'une lecture ---------------------------------


def test_a_search_is_an_exploration_and_a_keyed_read_is_not() -> None:
    """Le registre porte deja la difference, et personne ne la lisait."""

    registry = MCPToolRegistry()
    cherche = registry.get(SourceSystem.JIRA, "searchJiraIssuesUsingJql")
    lit = registry.get(SourceSystem.JIRA, "getJiraIssue")

    assert _is_exploration(cherche)
    assert not _is_exploration(lit)


def test_an_unknown_contract_is_not_treated_as_an_exploration() -> None:
    """Un nom inconnu est deja refuse ailleurs ; il ne doit pas en plus declencher
    un conseil de lecture."""

    assert not _is_exploration(None)


# --- Le rappel, et quand il se tait -------------------------------------------------


def test_a_jira_search_recalls_the_other_source() -> None:
    provider = ScriptedProvider(searching_jira(), answered("Voici le point."))
    agent = agent_for(provider, reads_of(SourceSystem.JIRA, "searchJiraIssuesUsingJql"))

    ask(agent, question=LARGE)

    rappel = rappels(provider)
    assert len(rappel) == 1
    assert "Confluence" in rappel[0]


def test_reading_a_named_ticket_recalls_nothing() -> None:
    """Une question sur un ticket precis n'a rien a gagner a ouvrir Confluence, et
    l'y envoyer allongerait une reponse qui allait bien."""

    provider = ScriptedProvider(proposing(), answered("KAN-1 parle de connexion."))
    agent = agent_for(provider, reads_of(SourceSystem.JIRA, "getJiraIssue"))

    ask(agent, question="Que contient le ticket KAN-1 ?")

    assert rappels(provider) == []


def test_the_recall_happens_once_even_after_several_searches() -> None:
    """Le repeter ferait grossir le fil sans rien ajouter."""

    provider = ScriptedProvider(
        searching_jira(),
        searching_jira("project = KAN ORDER BY created", call_id="c2"),
        answered("Voici le point."),
    )
    agent = agent_for(provider, reads_of(SourceSystem.JIRA, "searchJiraIssuesUsingJql"))

    ask(agent, question=LARGE, max_steps=6)

    assert len(rappels(provider)) == 1


def test_the_recall_names_what_each_source_carries() -> None:
    """Dire "va voir ailleurs" sans dire ce qu'on y trouve n'aide pas a choisir."""

    rendu = CROSS_SOURCE_TURN.format(
        explore="Jira", absente="Confluence", jira="Jira", confluence="Confluence"
    )

    assert "ce qui est en cours" in rendu
    assert "ce qui a ete decide" in rendu
    # Et il dit pourquoi cela compte : une reponse partielle ne s'annonce pas.
    assert "partielle" in rendu


def test_the_recall_asks_for_one_search_per_source() -> None:
    """Sur un essai reel, la meme recherche Jira a ete relancee trois fois avec des
    criteres differents -- trois lectures sur quatre brulees du meme cote. Le
    registre ne refuse que les repetitions a l'identique."""

    rendu = CROSS_SOURCE_TURN.format(
        explore="Jira", absente="Confluence", jira="Jira", confluence="Confluence"
    )

    assert "Une seule recherche par source suffit" in rendu


def test_a_disabled_source_is_never_recommended() -> None:
    """Conseiller une source eteinte enverrait le modele vers un refus, et lui
    ferait perdre l'etape qui restait."""

    provider = ScriptedProvider(searching_jira(), answered("Voici le point."))
    agent = agent_for(
        provider,
        reads_of(SourceSystem.JIRA, "searchJiraIssuesUsingJql"),
        offered_systems=(SourceSystem.JIRA,),
    )

    ask(agent, question=LARGE)

    assert rappels(provider) == []


def test_the_workflow_keeps_what_the_recall_leans_on() -> None:
    """Garde-fou : un renommage silencieux ferait passer les tests ci-dessus sur du
    code mort."""

    assert hasattr(AgentReadWorkflow, "answer")
    assert "{absente}" in CROSS_SOURCE_TURN
