from app.core.config import Settings
from app.mcp.domain import MCPProvider, ToolActionClass
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.registry import (
    ATLASSIAN_ENDPOINT,
    CONFLUENCE_SOURCE_ORIGIN,
    FIGMA_ENDPOINT,
    FIGMA_FILE_KEY,
    FIGMA_NODE_ID,
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
    "getConfluenceSpaces",
    "getPagesInConfluenceSpace",
    "getConfluencePage",
    "getConfluencePageDescendants",
    "searchConfluenceUsingCql",
}
FIGMA_TOOLS = {
    "whoami",
    "get_metadata",
    "get_design_context",
    "get_screenshot",
    "get_variable_defs",
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
    assert FIGMA_ENDPOINT == "https://mcp.figma.com/mcp"
    assert JIRA_SOURCE_ORIGIN == "https://andrianalyfanny-1786296714755.atlassian.net"
    assert CONFLUENCE_SOURCE_ORIGIN == "https://andrianalyfanny.atlassian.net"
    assert FIGMA_FILE_KEY == "Ie3SsqL1KetjinTDHcNm2D"
    assert FIGMA_NODE_ID == "36:114"
    for forbidden_field in (
        "mcp_atlassian_endpoint",
        "mcp_figma_endpoint",
        "mcp_jira_source_origin",
        "mcp_confluence_source_origin",
        "mcp_figma_file_key",
        "mcp_figma_node_id",
    ):
        assert forbidden_field not in Settings.model_fields
