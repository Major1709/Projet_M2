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
            "properties": {
                "summary": {"type": "string"},
                "projectKey": {"type": "string"},
            },
        },
        "container_argument": "projectKey",
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


# --- Les deux ecritures qui modifient un ticket existant ---------------------------


def test_a_comment_is_classified_as_an_update_not_a_creation() -> None:
    """Ce qui decide n'est pas la grammaire mais la revalidation.

    Un commentaire est bien cree, mais ce qu'il faut confirmer juste avant d'ecrire,
    c'est que LE TICKET existe toujours et n'a pas bouge depuis l'approbation. Classe
    en creation, la verification porterait sur le projet, ce qui ne dit rien du ticket.
    """

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "addCommentToJiraIssue")

    assert contrat is not None
    assert contrat.action_class is ToolActionClass.UPDATE
    assert contrat.resource_argument == "issueIdOrKey"


def test_the_comment_id_field_is_refused() -> None:
    """L'exclusion la plus importante du registre.

    ``commentId`` transforme l'ajout en MODIFICATION d'un commentaire existant. Un
    contrat annonce comme "ajouter un commentaire" pourrait alors en reecrire un
    autre, ecrit par quelqu'un d'autre, sans que l'ecran d'approbation le montre.
    """

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "addCommentToJiraIssue")
    assert contrat is not None

    assert "commentId" in contrat.provider_input_schema["properties"]
    assert "commentId" not in contrat.public_input_schema["properties"]


def test_a_hidden_comment_cannot_be_proposed() -> None:
    """``commentVisibility`` restreint qui verra le commentaire. Un humain qui approuve
    "ajouter un commentaire" ne s'attend pas a ce qu'il soit cache."""

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "addCommentToJiraIssue")
    assert contrat is not None

    assert "commentVisibility" not in contrat.public_input_schema["properties"]


def test_a_transition_cannot_smuggle_field_changes() -> None:
    """``fields`` et ``update`` permettent de modifier n'importe quel champ AU PASSAGE
    d'une transition -- le meme sac ouvert qu'additional_fields, en plus trompeur :
    l'humain approuve "passer KAN-2 en Termine" et l'appel pourrait reassigner le
    ticket ou vider sa description."""

    contrat = MCPMutationRegistry().get(SourceSystem.JIRA, "transitionJiraIssue")
    assert contrat is not None

    accepte = contrat.provider_input_schema["properties"]
    offert = contrat.public_input_schema["properties"]

    for dangereux in ("fields", "update", "historyMetadata"):
        assert dangereux in accepte
        assert dangereux not in offert
    assert set(offert) == {"issueIdOrKey", "transition"}


def test_the_issue_key_is_anchored() -> None:
    """Un identifiant de ticket a une forme. La borner empeche qu'une valeur libre
    parte vers le fournisseur au seul motif qu'elle est une chaine."""

    import re

    for outil in ("addCommentToJiraIssue", "transitionJiraIssue"):
        contrat = MCPMutationRegistry().get(SourceSystem.JIRA, outil)
        assert contrat is not None
        motif = contrat.public_input_schema["properties"]["issueIdOrKey"]["pattern"]
        assert re.match(motif, "KAN-2")
        assert not re.match(motif, "../autre")
        assert not re.match(motif, "kan-2")


def test_an_update_without_a_resource_argument_is_refused_at_construction() -> None:
    """Sans lui, la revalidation n'a rien a relire et refuserait tout -- ce qui se
    decouvrirait a la premiere execution plutot qu'au demarrage."""

    with pytest.raises(ValueError, match="must name its resource argument"):
        a_contract(action_class=ToolActionClass.UPDATE, container_argument=None)


def test_a_named_argument_must_exist_in_the_public_schema() -> None:
    """Une faute de frappe dans un nom d'argument rendrait la cible vide sans rien
    casser de visible."""

    with pytest.raises(ValueError, match="which it does not accept"):
        a_contract(title_argument="titreQuiNexistePas")


def test_every_declared_fingerprint_is_the_live_one() -> None:
    """Les trois releves en direct sur mcp.atlassian.com le 01/09/2026."""

    attendues = {
        "createJiraIssue": "828960eaf117a59f0b27b4e80fb6893f4091474d429815cb04a2b50f21e28cdc",
        "addCommentToJiraIssue": (
            "36311209ea980a82f1366eb4ac2e11317565fd093b5a6dafb5a862750252a37d"
        ),
        "transitionJiraIssue": (
            "f054dd3f56c2cdf39f1fd178acede2cce5e1bad1580ea6a385029a6e0ccb95bc"
        ),
        "createConfluencePage": (
            "ecd3fadf71d215eec0a3d7c5465426d3010cd3e79819470b307e5fbba9367f8b"
        ),
        "updateConfluencePage": (
            "88a6bfb22c7e9797c27324c80130da32693c1942752e830a1acb5cac9652debe"
        ),
    }

    for contrat in MCPMutationRegistry().contracts:
        assert contrat.provider_input_schema_sha256 == attendues[contrat.tool_name]


# --- Confluence -------------------------------------------------------------------


def test_the_body_format_is_imposed_by_the_server_not_chosen_by_the_model() -> None:
    """Le fournisseur interprete le corps en HTML par defaut. Laisser ce choix au
    modele, c'est accepter qu'un jour il ecrive du markdown dans un champ lu comme du
    HTML : la page s'affiche alors avec ses asterisques en clair, et personne ne l'a
    decide."""

    for outil in ("createConfluencePage", "updateConfluencePage"):
        contrat = MCPMutationRegistry().get(SourceSystem.CONFLUENCE, outil)
        assert contrat is not None
        assert dict(contrat.fixed_provider_arguments) == {"contentFormat": "markdown"}
        # Impose, donc jamais offert : sinon l'humain approuverait une valeur et une
        # autre partirait.
        assert "contentFormat" not in contrat.public_input_schema["properties"]


def test_a_fixed_argument_may_not_also_be_offered() -> None:
    with pytest.raises(ValueError, match="both fixes and offers"):
        a_contract(fixed_provider_arguments={"projectKey": "KAN"})


def test_a_new_page_cannot_be_made_private() -> None:
    """Un humain qui approuve "creer une page dans l'espace ENG" ne s'attend pas a ce
    qu'elle soit invisible pour l'equipe."""

    contrat = MCPMutationRegistry().get(SourceSystem.CONFLUENCE, "createConfluencePage")
    assert contrat is not None

    accepte = contrat.provider_input_schema["properties"]
    offert = contrat.public_input_schema["properties"]

    assert "isPrivate" in accepte
    for ecarte in ("isPrivate", "status", "contentType", "parentId", "subtype"):
        assert ecarte not in offert
    assert set(offert) == {"spaceId", "title", "body"}


def test_an_update_cannot_move_the_page() -> None:
    """Le refus le plus important de ce contrat : spaceId et parentId DEPLACENT la
    page. L'humain approuve "mettre a jour cette page" et elle changerait d'espace
    sans que rien ne l'annonce."""

    contrat = MCPMutationRegistry().get(SourceSystem.CONFLUENCE, "updateConfluencePage")
    assert contrat is not None

    accepte = contrat.provider_input_schema["properties"]
    offert = contrat.public_input_schema["properties"]

    for deplacement in ("spaceId", "parentId"):
        assert deplacement in accepte
        assert deplacement not in offert
    for autre in ("status", "versionMessage"):
        assert autre not in offert


def test_confluence_writes_use_the_confluence_binding() -> None:
    """Le liant choisit le cloudId injecte. Se tromper ferait ecrire sur le mauvais
    produit du meme site."""

    for outil in ("createConfluencePage", "updateConfluencePage"):
        contrat = MCPMutationRegistry().get(SourceSystem.CONFLUENCE, outil)
        assert contrat is not None
        assert contrat.binding_kind is MCPBindingKind.CONFLUENCE
        assert contrat.resource_type == "page"
