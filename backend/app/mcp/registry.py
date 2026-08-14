import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from string import Formatter
from typing import Any
from urllib.parse import quote

from app.mcp.domain import MCPBindingKind, MCPProvider, ToolActionClass
from app.mcp.domain import MCPReadSourceSystem as SourceSystem

ATLASSIAN_ENDPOINT = "https://mcp.atlassian.com/v1/mcp"
FIGMA_ENDPOINT = "https://mcp.figma.com/mcp"
# Where a delegated Atlassian grant is traded for a fresh one, from the server's
# own metadata at /.well-known/oauth-authorization-server. Pinned here rather than
# read from the credentials document: that file only has to be tampered with once
# to redirect a refresh token to an attacker, and the endpoint is not a per-install
# value. Re-check it if Atlassian ever moves the authorisation server.
ATLASSIAN_TOKEN_ENDPOINT = "https://cf.mcp.atlassian.com/v1/token"
# Same role for Figma, from its own metadata. Figma differs on one point that the
# renewal has to honour: it advertises only client_secret_basic / client_secret_post,
# never "none", so a Figma document carries a client secret where Atlassian's does not.
FIGMA_TOKEN_ENDPOINT = "https://api.figma.com/v1/oauth/token"
# One site now carries both products, so both origins are the same host. They stay
# declared separately because that is a property of this deployment, not of the
# protocol: Jira and Confluence can live on different sites, and a citation built
# from the wrong origin resolves to a foreign server rather than failing loudly.
# Verify against getAccessibleAtlassianResources when the deployment changes --
# that tool only lists the sites the presented token covers, so a single call is
# never proof that a site does not exist.
JIRA_SOURCE_ORIGIN = "https://andrianalyfanny.atlassian.net"
CONFLUENCE_SOURCE_ORIGIN = "https://andrianalyfanny.atlassian.net"
FIGMA_SOURCE_ORIGIN = "https://www.figma.com"
FIGMA_FILE_KEY = "Ie3SsqL1KetjinTDHcNm2D"
FIGMA_NODE_ID = "36:114"
MCP_POLICY_VERSION = "SPEC-MCP-RO-001-r2"
# Pinned deliberately: a remote server negotiates down to whatever the client
# accepts, so every entry added here widens what a provider can force on us.
# 2025-11-25 is the highest version the Atlassian MCP server currently speaks.
APPROVED_PROTOCOL_VERSIONS = frozenset({"2026-07-28", "2025-11-25"})

_NON_VALIDATION_SCHEMA_KEYS = frozenset(
    {"$schema", "$id", "default", "description", "examples", "title"}
)


def _semantic_schema(value: Any, *, parent_key: str | None = None) -> Any:
    """Canonicalize validation semantics while excluding documentation-only drift."""

    if isinstance(value, dict):
        if set(value) == {"json"} and isinstance(value["json"], dict):
            return _semantic_schema(value["json"])
        return {
            key: _semantic_schema(child, parent_key=key)
            for key, child in sorted(value.items())
            if key not in _NON_VALIDATION_SCHEMA_KEYS
        }
    if isinstance(value, list):
        normalized = [_semantic_schema(item, parent_key=parent_key) for item in value]
        if parent_key in {"enum", "required"} and all(
            isinstance(item, (str, int, float, bool, type(None))) for item in normalized
        ):
            return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
        return normalized
    return value


def canonical_schema_json(schema: dict[str, Any]) -> str:
    return json.dumps(
        _semantic_schema(schema),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def schema_sha256(schema: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_schema_json(schema).encode("utf-8")).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ToolContract:
    server_id: str
    provider: MCPProvider
    source_system: SourceSystem
    source_origin: str
    tool_name: str
    binding_kind: MCPBindingKind
    public_input_schema: dict[str, Any]
    provider_input_schema: dict[str, Any]
    provider_output_schema: dict[str, Any] | None = None
    action_class: ToolActionClass = ToolActionClass.READ
    policy_version: str = MCP_POLICY_VERSION
    # Citation path appended to ``source_origin``, holding exactly one ``{name}``
    # placeholder naming a required public argument. The value is therefore ours:
    # it is JSON-Schema validated before the call and never read back from the
    # provider response, so a compromised server cannot redirect a citation.
    resource_reference_path: str | None = None
    provider_input_schema_sha256: str = field(init=False)
    provider_output_schema_sha256: str | None = field(init=False)

    def __post_init__(self) -> None:
        if self.action_class != ToolActionClass.READ:
            raise ValueError("The read-only MCP registry cannot contain mutations")
        if self.resource_reference_path is not None:
            argument = self._resource_reference_argument()
            required = set(self.public_input_schema.get("required", ()))
            if argument not in required:
                raise ValueError(
                    f"{self.tool_name} cites {argument}, which is not a required public argument"
                )
        object.__setattr__(
            self,
            "provider_input_schema_sha256",
            schema_sha256(self.provider_input_schema),
        )
        object.__setattr__(
            self,
            "provider_output_schema_sha256",
            (
                schema_sha256(self.provider_output_schema)
                if self.provider_output_schema is not None
                else None
            ),
        )

    def _resource_reference_argument(self) -> str:
        assert self.resource_reference_path is not None
        names = [
            name
            for _, name, _, _ in Formatter().parse(self.resource_reference_path)
            if name is not None
        ]
        if len(names) != 1 or not names[0]:
            raise ValueError(
                f"{self.tool_name} needs exactly one named placeholder in its citation path"
            )
        return names[0]

    def resource_reference(self, arguments: Mapping[str, Any]) -> str | None:
        """Build the citation URL from our own validated arguments, or None.

        The reference is derived, never observed: the placeholder is filled from
        the caller's argument after JSON-Schema validation, then percent-encoded
        with no safe characters so a value cannot escape its path segment.
        """

        if self.resource_reference_path is None:
            return None
        argument = self._resource_reference_argument()
        value = arguments.get(argument)
        if not isinstance(value, str) or not value:
            return None
        path = self.resource_reference_path.format(**{argument: quote(value, safe="")})
        return f"{self.source_origin}{path}"


def _object_schema(
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _string(*, maximum: int | None = None, pattern: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "minLength": 1}
    if maximum is not None:
        schema["maxLength"] = maximum
    if pattern is not None:
        schema["pattern"] = pattern
    return schema


def _array(item: dict[str, Any], *, maximum: int) -> dict[str, Any]:
    return {"type": "array", "items": item, "maxItems": maximum, "uniqueItems": True}


_REMOTE_STRING = {"type": "string"}
_CLOUD_ID = {"type": "string"}
_EMPTY = _object_schema()
# Mirrors what the Atlassian server actually publishes for its argument-free
# tools: an open object, without the additionalProperties guard we impose on our
# own public contract. Provider schemas must reproduce the provider byte for
# byte, otherwise the drift check fires on a difference we invented ourselves.
_PROVIDER_EMPTY = {"type": "object", "properties": {}}

_ATLASSIAN_COMMON = (
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.ATLASSIAN,
        source_origin=ATLASSIAN_ENDPOINT,
        tool_name="atlassianUserInfo",
        binding_kind=MCPBindingKind.NONE,
        public_input_schema=_EMPTY,
        provider_input_schema=_PROVIDER_EMPTY,
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.ATLASSIAN,
        source_origin=ATLASSIAN_ENDPOINT,
        tool_name="getAccessibleAtlassianResources",
        binding_kind=MCPBindingKind.NONE,
        public_input_schema=_EMPTY,
        provider_input_schema=_PROVIDER_EMPTY,
    ),
)

_JIRA_CONTRACTS = (
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.JIRA,
        source_origin=JIRA_SOURCE_ORIGIN,
        tool_name="getVisibleJiraProjects",
        binding_kind=MCPBindingKind.JIRA,
        public_input_schema=_object_schema(
            {
                "searchString": _string(maximum=200),
                "action": {"type": "string", "enum": ["view", "browse"]},
                "startAt": {"type": "integer", "minimum": 0, "maximum": 10_000},
                "maxResults": {"type": "integer", "minimum": 1, "maximum": 50},
                "expandIssueTypes": {"type": "boolean"},
            }
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "searchString": _REMOTE_STRING,
                "action": {"type": "string", "enum": ["view", "browse", "edit", "create"]},
                "startAt": {"type": "number"},
                "maxResults": {"type": "number", "maximum": 50},
                "expandIssueTypes": {"type": "boolean"},
            },
            ("cloudId",),
        ),
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.JIRA,
        source_origin=JIRA_SOURCE_ORIGIN,
        tool_name="searchJiraIssuesUsingJql",
        binding_kind=MCPBindingKind.JIRA,
        public_input_schema=_object_schema(
            {
                "jql": _string(maximum=4_000),
                "maxResults": {"type": "integer", "minimum": 1, "maximum": 50},
                "fields": _array(_string(maximum=100), maximum=50),
                "nextPageToken": _string(maximum=4_096),
            },
            ("jql",),
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "jql": _REMOTE_STRING,
                "maxResults": {"type": "number", "maximum": 100},
                "fields": {"type": "array", "items": _REMOTE_STRING},
                "nextPageToken": _REMOTE_STRING,
                "responseContentFormat": {"type": "string", "enum": ["adf", "markdown"]},
                "searchResultMode": {"type": "string", "enum": ["all", "count", "issues"]},
            },
            ("cloudId", "jql"),
        ),
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.JIRA,
        source_origin=JIRA_SOURCE_ORIGIN,
        tool_name="getJiraIssue",
        binding_kind=MCPBindingKind.JIRA,
        public_input_schema=_object_schema(
            {
                "issueIdOrKey": _string(maximum=255),
                "fields": _array(_string(maximum=100), maximum=50),
                "fieldsByKeys": {"type": "boolean"},
                "expand": _string(maximum=255),
                "properties": _array(_string(maximum=100), maximum=50),
                "failFast": {"type": "boolean"},
            },
            ("issueIdOrKey",),
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "issueIdOrKey": _REMOTE_STRING,
                "fields": {"type": "array", "items": _REMOTE_STRING},
                "fieldsByKeys": {"type": "boolean"},
                "expand": _REMOTE_STRING,
                "properties": {"type": "array", "items": _REMOTE_STRING},
                "updateHistory": {"type": "boolean"},
                "failFast": {"type": "boolean"},
                "responseContentFormat": {"type": "string", "enum": ["adf", "markdown"]},
            },
            ("cloudId", "issueIdOrKey"),
        ),
        resource_reference_path="/browse/{issueIdOrKey}",
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.JIRA,
        source_origin=JIRA_SOURCE_ORIGIN,
        tool_name="getJiraIssueRemoteIssueLinks",
        binding_kind=MCPBindingKind.JIRA,
        public_input_schema=_object_schema(
            {
                "issueIdOrKey": _string(maximum=255),
                "globalId": _string(maximum=1_000),
            },
            ("issueIdOrKey",),
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "issueIdOrKey": _REMOTE_STRING,
                "globalId": _REMOTE_STRING,
            },
            ("cloudId", "issueIdOrKey"),
        ),
        resource_reference_path="/browse/{issueIdOrKey}",
    ),
)

_CONFLUENCE_CONTRACTS = (
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.CONFLUENCE,
        source_origin=CONFLUENCE_SOURCE_ORIGIN,
        tool_name="getConfluenceSpaces",
        binding_kind=MCPBindingKind.CONFLUENCE,
        public_input_schema=_object_schema(
            {
                "keys": _array(_string(maximum=255), maximum=50),
                "type": {"type": "string", "enum": ["global", "personal"]},
                "status": {"type": "string", "enum": ["current", "archived"]},
                "labels": _array(_string(maximum=255), maximum=50),
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "ids": {
                    "anyOf": [
                        _REMOTE_STRING,
                        {"type": "array", "items": {"type": "number"}},
                    ]
                },
                "keys": {
                    "anyOf": [
                        _REMOTE_STRING,
                        {"type": "array", "items": _REMOTE_STRING},
                    ]
                },
                "type": {"type": "string", "enum": ["global", "personal"]},
                "status": {"type": "string", "enum": ["current", "archived"]},
                "labels": {
                    "anyOf": [
                        _REMOTE_STRING,
                        {"type": "array", "items": _REMOTE_STRING},
                    ]
                },
                "expand": {
                    "anyOf": [
                        _REMOTE_STRING,
                        {"type": "array", "items": _REMOTE_STRING},
                    ]
                },
                "favoritedBy": _REMOTE_STRING,
                "favourite": {"type": "boolean"},
                "start": {"type": "number"},
                "limit": {"type": "number"},
            },
            ("cloudId",),
        ),
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.CONFLUENCE,
        source_origin=CONFLUENCE_SOURCE_ORIGIN,
        tool_name="getPagesInConfluenceSpace",
        binding_kind=MCPBindingKind.CONFLUENCE,
        public_input_schema=_object_schema(
            {
                "spaceId": _string(maximum=255),
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "cursor": _string(maximum=4_096),
                "status": {
                    "type": "string",
                    "enum": ["current", "archived", "deleted", "trashed"],
                },
                "title": _string(maximum=500),
                "sort": {
                    "type": "string",
                    "enum": [
                        "id",
                        "-id",
                        "created-date",
                        "-created-date",
                        "modified-date",
                        "-modified-date",
                        "title",
                        "-title",
                    ],
                },
            },
            ("spaceId",),
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "spaceId": _REMOTE_STRING,
                "limit": {"type": "integer", "minimum": 1, "maximum": 250},
                "cursor": _REMOTE_STRING,
                "status": {
                    "type": "string",
                    "enum": ["current", "archived", "deleted", "trashed"],
                },
                "title": _REMOTE_STRING,
                "sort": {
                    "type": "string",
                    "enum": [
                        "id",
                        "-id",
                        "created-date",
                        "-created-date",
                        "modified-date",
                        "-modified-date",
                        "title",
                        "-title",
                    ],
                },
                "contentFormat": {"type": "string", "enum": ["adf", "markdown"]},
                "contentType": {"type": "string", "enum": ["blog", "page"]},
            },
            ("cloudId", "spaceId"),
        ),
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.CONFLUENCE,
        source_origin=CONFLUENCE_SOURCE_ORIGIN,
        tool_name="getConfluencePage",
        binding_kind=MCPBindingKind.CONFLUENCE,
        public_input_schema=_object_schema(
            {
                "pageId": _string(maximum=255),
                "contentFormat": {"type": "string", "enum": ["markdown", "adf"]},
            },
            ("pageId",),
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "pageId": _REMOTE_STRING,
                "contentFormat": {"type": "string", "enum": ["adf", "html", "markdown"]},
                "contentType": {"type": "string", "enum": ["blog", "page"]},
            },
            ("cloudId", "pageId"),
        ),
        resource_reference_path="/wiki/pages/{pageId}",
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.CONFLUENCE,
        source_origin=CONFLUENCE_SOURCE_ORIGIN,
        tool_name="getConfluencePageDescendants",
        binding_kind=MCPBindingKind.CONFLUENCE,
        public_input_schema=_object_schema(
            {
                "pageId": _string(maximum=255),
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "depth": {"type": "integer", "minimum": 1, "maximum": 10},
                "cursor": _string(maximum=4_096),
            },
            ("pageId",),
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "pageId": _REMOTE_STRING,
                "limit": {"type": "number"},
                "depth": {"type": "number"},
                "cursor": _REMOTE_STRING,
            },
            ("cloudId", "pageId"),
        ),
        resource_reference_path="/wiki/pages/{pageId}",
    ),
    ToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.CONFLUENCE,
        source_origin=CONFLUENCE_SOURCE_ORIGIN,
        tool_name="searchConfluenceUsingCql",
        binding_kind=MCPBindingKind.CONFLUENCE,
        public_input_schema=_object_schema(
            {
                "cql": _string(maximum=4_000),
                "cqlcontext": _string(maximum=1_000),
                "cursor": _string(maximum=4_096),
                "expand": _string(maximum=500),
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ("cql",),
        ),
        provider_input_schema=_object_schema(
            {
                "cloudId": _CLOUD_ID,
                "cql": _REMOTE_STRING,
                "cqlcontext": _REMOTE_STRING,
                "cursor": _REMOTE_STRING,
                "expand": _REMOTE_STRING,
                "limit": {"type": "number"},
                "prev": {"type": "boolean"},
                "next": {"type": "boolean"},
            },
            ("cloudId", "cql"),
        ),
    ),
)

_FIGMA_CONTEXT_PROPERTIES = {
    "fileKey": _REMOTE_STRING,
    "nodeId": _REMOTE_STRING,
    "clientLanguages": _REMOTE_STRING,
    "clientFrameworks": _REMOTE_STRING,
}

_FIGMA_CONTRACTS = (
    ToolContract(
        server_id="figma-remote",
        provider=MCPProvider.FIGMA,
        source_system=SourceSystem.FIGMA,
        source_origin=FIGMA_SOURCE_ORIGIN,
        tool_name="whoami",
        binding_kind=MCPBindingKind.NONE,
        public_input_schema=_EMPTY,
        provider_input_schema=_EMPTY,
    ),
    ToolContract(
        server_id="figma-remote",
        provider=MCPProvider.FIGMA,
        source_system=SourceSystem.FIGMA,
        source_origin=FIGMA_SOURCE_ORIGIN,
        tool_name="get_metadata",
        binding_kind=MCPBindingKind.FIGMA,
        public_input_schema=_EMPTY,
        provider_input_schema=_object_schema(
            dict(_FIGMA_CONTEXT_PROPERTIES),
            ("fileKey", "nodeId"),
        ),
    ),
    ToolContract(
        server_id="figma-remote",
        provider=MCPProvider.FIGMA,
        source_system=SourceSystem.FIGMA,
        source_origin=FIGMA_SOURCE_ORIGIN,
        tool_name="get_design_context",
        binding_kind=MCPBindingKind.FIGMA,
        public_input_schema=_EMPTY,
        provider_input_schema=_object_schema(
            {
                **_FIGMA_CONTEXT_PROPERTIES,
                "excludeScreenshot": {"type": "boolean"},
                "forceCode": {"type": "boolean"},
                "disableCodeConnect": {"type": "boolean"},
            },
            ("fileKey", "nodeId"),
        ),
    ),
    ToolContract(
        server_id="figma-remote",
        provider=MCPProvider.FIGMA,
        source_system=SourceSystem.FIGMA,
        source_origin=FIGMA_SOURCE_ORIGIN,
        tool_name="get_screenshot",
        binding_kind=MCPBindingKind.FIGMA,
        public_input_schema=_EMPTY,
        provider_input_schema=_object_schema(
            dict(_FIGMA_CONTEXT_PROPERTIES),
            ("fileKey", "nodeId"),
        ),
    ),
    ToolContract(
        server_id="figma-remote",
        provider=MCPProvider.FIGMA,
        source_system=SourceSystem.FIGMA,
        source_origin=FIGMA_SOURCE_ORIGIN,
        tool_name="get_variable_defs",
        binding_kind=MCPBindingKind.FIGMA,
        public_input_schema=_EMPTY,
        provider_input_schema=_object_schema(
            dict(_FIGMA_CONTEXT_PROPERTIES),
            ("fileKey", "nodeId"),
        ),
    ),
)


class MCPToolRegistry:
    def __init__(self, contracts: tuple[ToolContract, ...] | None = None) -> None:
        selected = contracts or (
            *_ATLASSIAN_COMMON,
            *_JIRA_CONTRACTS,
            *_CONFLUENCE_CONTRACTS,
            *_FIGMA_CONTRACTS,
        )
        indexed: dict[tuple[SourceSystem, str], ToolContract] = {}
        for contract in selected:
            key = (contract.source_system, contract.tool_name)
            if key in indexed:
                raise ValueError("Duplicate MCP tool contract")
            indexed[key] = contract
        self._contracts = indexed

    @property
    def contracts(self) -> tuple[ToolContract, ...]:
        return tuple(self._contracts.values())

    def get(self, source_system: SourceSystem, tool_name: str) -> ToolContract | None:
        return self._contracts.get((source_system, tool_name))
