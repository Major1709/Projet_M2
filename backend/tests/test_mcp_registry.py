from app.core.config import Settings
from app.mcp.domain import MCPProvider, ToolActionClass
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.registry import (
    ATLASSIAN_ENDPOINT,
    CONFLUENCE_SOURCE_ORIGIN,
    FIGMA_REFERENCE_FILE_KEY,
    FIGMA_REST_ENDPOINT,
    JIRA_SOURCE_ORIGIN,
    MCPToolRegistry,
    schema_sha256,
)

ATLASSIAN_TOOLS = {
    "atlassianUserInfo",
    "getAccessibleAtlassianResources",
    "getVisibleJiraProjects",
    "searchJiraIssuesUsingJql",
    "getJiraIssue",
    "getJiraIssueRemoteIssueLinks",
    # Ajoute avec transitionJiraIssue, et indispensable a lui : une transition se
    # designe par un identifiant numerique que seule cette lecture publie.
    "getTransitionsForJiraIssue",
    "getConfluenceSpaces",
    "getPagesInConfluenceSpace",
    "getConfluencePage",
    "getConfluencePageDescendants",
    "searchConfluenceUsingCql",
}
FIGMA_TOOLS = {
    "getFigmaFile",
    "getFigmaNode",
    "renderFigmaNode",
    "extractFigmaProcess",
}


def test_registry_contains_only_the_approved_read_allowlist() -> None:
    registry = MCPToolRegistry()
    atlassian = {
        contract.tool_name
        for contract in registry.contracts
        if contract.provider == MCPProvider.ATLASSIAN
    }
    figma = {
        contract.tool_name
        for contract in registry.contracts
        if contract.provider == MCPProvider.FIGMA
    }

    assert atlassian == ATLASSIAN_TOOLS
    assert figma == FIGMA_TOOLS
    assert all(contract.action_class == ToolActionClass.READ for contract in registry.contracts)
    assert all(len(contract.provider_input_schema_sha256) == 64 for contract in registry.contracts)
    assert registry.get(SourceSystem.FIGMA, "use_figma") is None
    assert registry.get(SourceSystem.JIRA, "createJiraIssue") is None


def test_schema_fingerprint_ignores_only_documentation_and_order() -> None:
    schema = {
        "type": "object",
        "description": "provider prose",
        "properties": {"value": {"type": "string", "description": "prose"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    reordered_and_wrapped = {
        "json": {
            "additionalProperties": False,
            "required": ["value"],
            "properties": {"value": {"description": "changed", "type": "string"}},
            "type": "object",
        }
    }
    derived = {
        **schema,
        "properties": {
            **schema["properties"],
            "derived": {"type": "string"},
        },
    }

    assert schema_sha256(schema) == schema_sha256(reordered_and_wrapped)
    assert schema_sha256(schema) != schema_sha256(derived)


def test_endpoints_origins_and_figma_target_are_fixed_not_configurable() -> None:
    assert ATLASSIAN_ENDPOINT == "https://mcp.atlassian.com/v1/mcp"
    assert FIGMA_REST_ENDPOINT == "https://api.figma.com"
    # Both products are hosted on one site in this deployment, so both origins are
    # that site. An origin that drifts from the site actually read makes every
    # citation resolve to a foreign server instead of failing loudly, which is why
    # these are asserted rather than derived from configuration.
    assert JIRA_SOURCE_ORIGIN == "https://andrianalyfanny.atlassian.net"
    assert CONFLUENCE_SOURCE_ORIGIN == "https://andrianalyfanny.atlassian.net"
    assert FIGMA_REFERENCE_FILE_KEY == "UVQmgXGaZC5vrtaQRU5nvo"
    for forbidden_field in (
        "mcp_atlassian_endpoint",
        "mcp_figma_endpoint",
        "mcp_jira_source_origin",
        "mcp_confluence_source_origin",
        "mcp_figma_file_key",
        "mcp_figma_node_id",
    ):
        assert forbidden_field not in Settings.model_fields


# --- L'empreinte de derive et les proprietes qui portent un nom de mot-cle ---------


def test_a_property_named_description_is_covered_by_the_fingerprint() -> None:
    """Le defaut que ce test ferme.

    ``_semantic_schema`` retirait toute cle nommee ``description`` a n'importe quelle
    profondeur, sans distinguer l'annotation du mot-cle d'une propriete qui porte ce
    nom. Or ``createJiraIssue`` declare une propriete ``description``, et
    ``getPagesInConfluenceSpace`` une propriete ``title`` : ces champs disparaissaient
    de l'empreinte, et un fournisseur pouvait les changer sans que le controle de
    derive ne voie rien -- exactement ce qu'il existe pour empecher.
    """

    avec = {
        "type": "object",
        "properties": {"description": {"type": "string"}},
    }
    sans = {"type": "object", "properties": {}}

    assert schema_sha256(avec) != schema_sha256(sans)


def test_changing_the_type_of_such_a_property_changes_the_fingerprint() -> None:
    chaine = {"type": "object", "properties": {"title": {"type": "string"}}}
    nombre = {"type": "object", "properties": {"title": {"type": "number"}}}

    assert schema_sha256(chaine) != schema_sha256(nombre)


def test_documentation_drift_still_does_not_move_the_fingerprint() -> None:
    """Le pendant : l'annotation reste ignoree, sinon chaque reformulation de prose
    chez le fournisseur casserait le controle et on finirait par le desactiver."""

    avant = {"type": "string", "description": "Une prose qui peut changer"}
    apres = {"type": "string", "description": "Une autre prose"}

    assert schema_sha256(avant) == schema_sha256(apres)


def test_the_distinction_holds_at_depth() -> None:
    """Une propriete nommee comme un mot-cle, imbriquee sous une autre."""

    profond = {
        "type": "object",
        "properties": {
            "fields": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            }
        },
    }
    ampute = {
        "type": "object",
        "properties": {"fields": {"type": "object", "properties": {}}},
    }

    assert schema_sha256(profond) != schema_sha256(ampute)


# --- Ce qui a ete approuve le 30/09/2026 -------------------------------------------
#
# Atlassian a ajoute "actionSource" a ses trois outils Jira. La derive a ete
# constatee par le controle d'empreinte, qui a refuse toutes les lectures Jira
# jusqu'a ce que le changement soit lu.
#
# Ces tests ne verifient pas que le champ existe -- ils fixent ce qui a ete approuve
# EN L'ACCEPTANT : facultatif, jamais offert au modele. Si une prochaine derive le
# rendait obligatoire ou l'exposait, ces tests tomberaient, et c'est leur seul but.

JIRA_TOOLS_WITH_ACTION_SOURCE = (
    "getJiraIssue",
    "searchJiraIssuesUsingJql",
    "getTransitionsForJiraIssue",
)


def test_the_provider_schema_carries_the_field_atlassian_added() -> None:
    """Sans lui, l'empreinte ne correspond plus et toute lecture Jira est refusee."""

    registry = MCPToolRegistry()

    for nom in JIRA_TOOLS_WITH_ACTION_SOURCE:
        contract = registry.get(SourceSystem.JIRA, nom)
        assert contract is not None, nom
        assert "actionSource" in contract.provider_input_schema["properties"], nom


def test_the_added_field_is_optional() -> None:
    """Un champ devenu obligatoire ne serait plus une derive documentaire : nos appels
    existants cesseraient d'etre valides, et l'accepter en silence les casserait."""

    registry = MCPToolRegistry()

    for nom in JIRA_TOOLS_WITH_ACTION_SOURCE:
        contract = registry.get(SourceSystem.JIRA, nom)
        assert contract is not None, nom
        assert "actionSource" not in contract.provider_input_schema.get("required", []), nom


def test_the_added_field_is_never_offered_to_the_model() -> None:
    """Le schema public est ce que le modele voit et peut remplir. Un champ
    d'attribution choisi par le modele dirait au fournisseur ce qu'on veut, et non ce
    qui est -- et le catalogue public n'existe que pour ne rien offrir de plus que le
    strict necessaire."""

    registry = MCPToolRegistry()

    for nom in JIRA_TOOLS_WITH_ACTION_SOURCE:
        contract = registry.get(SourceSystem.JIRA, nom)
        assert contract is not None, nom
        assert "actionSource" not in contract.public_input_schema["properties"], nom


def test_the_required_arguments_did_not_move() -> None:
    """La verification qui autorisait l'approbation : aucun argument obligatoire n'a
    change, donc les lectures d'avant restent exactement aussi valides."""

    registry = MCPToolRegistry()
    attendu = {
        "getJiraIssue": {"cloudId", "issueIdOrKey"},
        "searchJiraIssuesUsingJql": {"cloudId", "jql"},
        "getTransitionsForJiraIssue": {"cloudId", "issueIdOrKey"},
    }

    for nom, requis in attendu.items():
        contract = registry.get(SourceSystem.JIRA, nom)
        assert contract is not None, nom
        assert set(contract.provider_input_schema["required"]) == requis, nom
