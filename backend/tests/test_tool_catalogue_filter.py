"""Ce qui est offert au modele suit ce qui est reellement branche.

Le catalogue presentait les quatre outils Figma alors que le connecteur est eteint.
Deux couts : environ 430 tokens payes a chaque appel sur un prompt qui en coute
2 065, et surtout un choix propose au modele qui ne pouvait qu'echouer. Offrir une
porte fermee n'est pas neutre, c'est inviter a la prendre.
"""

import pytest

from app.agent.read_workflow import AgentReadWorkflow, tool_catalogue
from app.bootstrap import _offered_systems
from app.core.config import Settings
from app.mcp.domain import MCPReadSourceSystem
from app.mcp.registry import MCPToolRegistry

CLOUD = "a761589f-69b8-4373-9c30-7561c2d45a39"


def settings_for(**flags: bool) -> Settings:
    base = {
        "environment": "test",
        "mcp_atlassian_enabled": True,
        "mcp_jira_enabled": True,
        "mcp_confluence_enabled": True,
        "mcp_figma_enabled": False,
        "mcp_atlassian_jira_cloud_id": CLOUD,
        "mcp_atlassian_confluence_cloud_id": CLOUD,
    }
    base.update(flags)
    return Settings(**base)


def names(catalogue) -> set[str]:
    return {entry["function"]["name"] for entry in catalogue}


def test_a_disabled_connector_is_not_offered() -> None:
    filtre = tool_catalogue(MCPToolRegistry(), _offered_systems(settings_for()))

    assert not any(nom.lower().startswith(("getfigma", "renderfigma", "extractfigma"))
                   for nom in names(filtre))


def test_the_shared_atlassian_tools_follow_the_platform_not_a_product() -> None:
    """Le defaut que la mesure a revele.

    ``atlassianUserInfo`` et ``getAccessibleAtlassianResources`` portent le systeme
    ATLASSIAN, qui n'existe pas dans l'autre enumeration de systemes du projet. Un
    filtre ecrit sur la mauvaise laissait passer jira et confluence par simple
    egalite de chaines -- les deux sont des ``StrEnum`` -- et faisait tomber ces deux
    outils en silence.
    """

    offerts = names(tool_catalogue(MCPToolRegistry(), _offered_systems(settings_for())))

    assert "atlassianUserInfo" in offerts
    assert "getAccessibleAtlassianResources" in offerts


def test_disabling_the_platform_removes_the_shared_tools() -> None:
    """Le pendant du test precedent : ils suivent le socle, donc ils partent avec lui."""

    eteint = _offered_systems(
        settings_for(
            mcp_atlassian_enabled=False, mcp_jira_enabled=False, mcp_confluence_enabled=False
        )
    )

    assert eteint == frozenset()


def test_the_filter_only_hides_and_never_widens() -> None:
    """La propriete qui rend ce filtre sur : il est un sous-ensemble strict."""

    registre = MCPToolRegistry()
    tout = names(tool_catalogue(registre))
    filtre = names(tool_catalogue(registre, _offered_systems(settings_for())))

    assert filtre < tout


def test_no_filter_offers_everything() -> None:
    """Le comportement d'avant ce parametre, conserve tel quel."""

    registre = MCPToolRegistry()

    assert tool_catalogue(registre) == tool_catalogue(registre, None)


def test_a_hidden_tool_is_still_recognised_by_the_workflow() -> None:
    """La distinction qui justifie de filtrer le catalogue et non le registre.

    Un modele qui nomme un outil Figma malgre tout doit etre reconnu, puis refuse par
    son connecteur eteint avec sa vraie raison -- pas traite en outil inconnu, ce qui
    dirait au modele qu'il a invente un nom alors qu'il a nomme une porte fermee.
    """

    workflow = AgentReadWorkflow.__new__(AgentReadWorkflow)
    workflow._registry = MCPToolRegistry()
    from app.agent.read_workflow import _index_by_tool_name

    workflow._contracts = _index_by_tool_name(workflow._registry)

    assert "getFigmaFile" in workflow._contracts


@pytest.mark.parametrize(
    ("drapeau", "systeme"),
    [
        ("mcp_jira_enabled", MCPReadSourceSystem.JIRA),
        ("mcp_confluence_enabled", MCPReadSourceSystem.CONFLUENCE),
        ("mcp_figma_enabled", MCPReadSourceSystem.FIGMA),
    ],
)
def test_each_flag_governs_its_own_system(drapeau: str, systeme) -> None:
    """Derive des memes drapeaux qui autorisent une lecture, et d'eux seuls : deux
    listes decrivant la meme decision divergent."""

    assert systeme in _offered_systems(settings_for(**{drapeau: True}))
    assert systeme not in _offered_systems(settings_for(**{drapeau: False}))
