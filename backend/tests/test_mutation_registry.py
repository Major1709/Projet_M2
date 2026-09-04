"""Les ecritures declarees, et ce qui les empeche de deraper.

Le registre de lecture refuse tout contrat non-READ, et cette invariante est ce qui
rend le chemin de lecture digne de confiance. Ce registre-ci porte l'invariante
inverse, de sorte que chacun garde la sienne au lieu qu'un booleen les separe.
"""

import json

import pytest

from app.approvals.adapters.tool_pin import NoMutationToolsPin, RegistryMutationToolPin
from app.approvals.errors import InvalidTransition
from app.mcp.domain import MCPBindingKind, MCPProvider, ToolActionClass
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.mutation_registry import MCPMutationRegistry, MutationToolContract
from app.mcp.registry import MCPToolRegistry, schema_sha256


def a_contract(**changes) -> MutationToolContract:
    base = {
        "server_id": "atlassian-rovo",
        "provider": MCPProvider.ATLASSIAN,
        "source_system": SourceSystem.JIRA,
        "source_origin": "https://exemple.atlassian.net",
        "tool_name": "createJiraIssue",
        "binding_kind": MCPBindingKind.JIRA,
        "action_class": ToolActionClass.CREATE,
        "public_input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
        "provider_input_schema": {
            "type": "object",
            "properties": {"cloudId": {"type": "string"}},
        },
    }
    base.update(changes)
    return MutationToolContract(**base)


def test_the_two_registries_cannot_hold_each_others_contracts() -> None:
    """L'invariante inverse, verifiee a la construction des deux cotes."""

    with pytest.raises(ValueError, match="cannot contain reads"):
        a_contract(action_class=ToolActionClass.READ)

    lectures = MCPToolRegistry().contracts
    assert all(c.action_class is ToolActionClass.READ for c in lectures)
    assert all(
        c.action_class is not ToolActionClass.READ for c in MCPMutationRegistry().contracts
    )


def test_a_public_schema_may_not_name_the_binding() -> None:
    """Le liant est injecte cote serveur apres l'approbation. Un schema public qui
    nommerait cloudId laisserait designer un autre site que celui du locataire."""

    with pytest.raises(ValueError, match="must not expose cloudId"):
        a_contract(
            public_input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"cloudId": {"type": "string"}},
            }
        )


def test_a_public_schema_must_be_closed() -> None:
    """Un schema ouvert rendrait l'approbation menteuse : l'humain verrait trois
    champs et la proposition pourrait en porter dix."""

    with pytest.raises(ValueError, match="must close its public schema"):
        a_contract(
            public_input_schema={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            }
        )


def test_the_declared_surface_is_narrower_than_the_provider_accepts() -> None:
    """Le refus qui compte.

    Le serveur decrit ``additional_fields`` comme le SEUL moyen de fixer la priorite,
    les etiquettes, les composants et n'importe quel champ personnalise -- un sac
    ouvert. Une proposition qui le porterait afficherait "creer un ticket intitule X"
    a l'humain tout en pouvant ecrire ailleurs.
    """

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "createJiraIssue")
    assert contrat is not None

    offerts = set(contrat.public_input_schema["properties"])
    acceptes = set(contrat.provider_input_schema["properties"])

    assert offerts == {"projectKey", "issueTypeName", "summary", "description"}
    assert offerts < acceptes
    for dangereux in ("additional_fields", "parent", "assignee_account_id", "transition"):
        assert dangereux in acceptes
        assert dangereux not in offerts


def test_the_pinned_fingerprint_is_the_one_the_live_server_publishes() -> None:
    """Releve en direct le 01/09/2026 depuis mcp.atlassian.com.

    Fige plutot que recalcule : si le fournisseur change la forme de l'outil, ce test
    echoue et quelqu'un doit regarder -- ce qui est precisement le but d'un epinglage.
    """

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "createJiraIssue")

    assert contrat is not None
    assert (
        contrat.provider_input_schema_sha256
        == "828960eaf117a59f0b27b4e80fb6893f4091474d429815cb04a2b50f21e28cdc"
    )


def test_the_project_key_is_anchored_and_not_merely_a_string() -> None:
    """Le motif empeche qu'une valeur libre parte vers le fournisseur au seul motif
    qu'elle est une chaine."""

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "createJiraIssue")
    assert contrat is not None

    motif = contrat.public_input_schema["properties"]["projectKey"]["pattern"]

    import re

    assert re.match(motif, "KAN")
    assert not re.match(motif, "kan")
    assert not re.match(motif, "../../autre")


def test_a_duplicate_contract_is_refused() -> None:
    with pytest.raises(ValueError, match="Duplicate MCP mutation contract"):
        MCPMutationRegistry((a_contract(), a_contract()))


def test_an_empty_registry_is_a_legitimate_state() -> None:
    """Un deploiement qui n'autorise aucune ecriture n'est pas en panne."""

    vide = MCPMutationRegistry(())

    assert vide.contracts == ()
    assert vide.get(SourceSystem.JIRA, "createJiraIssue") is None


def test_the_pin_resolves_a_declared_tool() -> None:
    epingle = RegistryMutationToolPin()

    empreinte = epingle.schema_sha256(
        source_system=SourceSystem.JIRA, tool_name="createJiraIssue"
    )

    assert len(empreinte) == 64


def test_the_pin_denies_an_undeclared_tool() -> None:
    """Refus par defaut. Inventer une empreinte laisserait une proposition revendiquer
    une forme que personne n'a publiee, et l'approbation porterait sur une fiction."""

    epingle = RegistryMutationToolPin()

    with pytest.raises(InvalidTransition, match="No mutation contract"):
        epingle.schema_sha256(source_system=SourceSystem.JIRA, tool_name="deleteJiraProject")


def test_a_read_tool_has_no_mutation_pin() -> None:
    """Le nom existe dans l'autre registre, ce qui ne lui donne aucun droit ici."""

    with pytest.raises(InvalidTransition):
        RegistryMutationToolPin().schema_sha256(
            source_system=SourceSystem.JIRA, tool_name="getJiraIssue"
        )


def test_the_denying_pin_still_denies_everything() -> None:
    """Conserve pour les deploiements sans surface d'ecriture."""

    with pytest.raises(InvalidTransition):
        NoMutationToolsPin().schema_sha256(
            source_system=SourceSystem.JIRA, tool_name="createJiraIssue"
        )


def test_the_provider_schema_is_copied_and_not_simplified() -> None:
    """Un schema simplifie pour la lisibilite ferait echouer le controle de derive a
    chaque appel, et un controle qui se declenche a tort finit par etre desactive."""

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "createJiraIssue")
    assert contrat is not None

    # La canonicalisation est idempotente : recalculer sur le schema declare doit
    # redonner la meme empreinte que celle derivee a la construction.
    assert schema_sha256(json.loads(json.dumps(contrat.provider_input_schema))) == (
        contrat.provider_input_schema_sha256
    )
