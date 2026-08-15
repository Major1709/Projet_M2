"""Figma reads served by the Figma REST API behind the MCP read contract.

Why this exists rather than a Figma MCP client. Figma's MCP server admits only
clients registered in its catalogue; its dynamic registration endpoint answers 403
to everyone else, and its authorisation server advertises no public client method,
so no OAuth flow this backend can perform will ever succeed. The blockage is
administrative and nothing in this repository can lift it.

The REST API has no such gate, and it fits the existing pipeline without weakening
it. ``https://api.figma.com`` is a public HTTPS host on 443, so the address and
endpoint guards apply unchanged -- no exception to the anti-SSRF control had to be
carved out, which is what a self-hosted MCP server inside Docker would have cost.

What is deliberately given up. This adapter publishes the tool schemas it serves,
and the registry hashes them, so the drift check compares two things we both own.
That is weaker than checking a third party's contract, but it is not nothing: the
two declarations are written separately and on purpose, so editing one without the
other fails the read rather than passing silently.

Read-only is a property of the API here, not only of our policy: the Figma REST
API exposes no endpoint that creates or edits a node.
"""

import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import anyio
import httpx2

from app.core.identity import SecurityContext
from app.mcp.adapters.grants import DelegatedGrantBroker
from app.mcp.adapters.http_guard import (
    CALL_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    HTTPS_PORT,
    EndpointResolver,
    SystemEndpointResolver,
    is_approved_public_address,
    reject_oversized_response,
    validate_fixed_endpoint,
)
from app.mcp.domain import MCPBindingKind, MCPProvider
from app.mcp.errors import (
    MCPCallTimeout,
    MCPDNSRejected,
    MCPGrantUnavailable,
    MCPInvalidResponse,
    MCPRateLimited,
    MCPRemoteToolFailure,
    MCPToolDenied,
    MCPTransportFailure,
)
from app.mcp.ports import (
    MCPReadSession,
    RemoteContentBlock,
    RemoteToolDescription,
    RemoteToolResult,
)
from app.mcp.registry import FIGMA_REST_ENDPOINT, FIGMA_REST_PROTOCOL_VERSION

validate_fixed_endpoint(FIGMA_REST_ENDPOINT)

logger = logging.getLogger(__name__)

FigmaCredentialKind = Literal["personal_access_token", "oauth"]

_FILE_KEY = {
    "type": "string",
    "minLength": 10,
    "maxLength": 64,
    "pattern": r"^[A-Za-z0-9]+$",
}
_NODE_ID = {"type": "string", "minLength": 3, "maxLength": 64, "pattern": r"^\d+[:-]\d+$"}
_DEPTH = {"type": "integer", "minimum": 1, "maximum": 6}
_SCALE = {"type": "number", "minimum": 0.5, "maximum": 4}


_PROCESS_STEP = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "label", "kind"],
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "kind": {
            "type": "string",
            "enum": ["start", "end", "step", "decision", "terminal"],
        },
        "shape": {"type": "string"},
        "section": {"type": ["string", "null"]},
    },
}
_PROCESS_TRANSITION = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "from", "to"],
    "properties": {
        "id": {"type": "string"},
        "from": {"type": ["string", "null"]},
        "to": {"type": ["string", "null"]},
        "condition": {"type": ["string", "null"]},
    },
}
_PROCESS_NOTE = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "text"],
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "section": {"type": ["string", "null"]},
    },
}
_PROCESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["file", "steps", "transitions", "notes"],
    "properties": {
        "file": {
            "type": "object",
            "additionalProperties": False,
            "required": ["key", "name"],
            "properties": {
                "key": {"type": "string"},
                "name": {"type": "string"},
                "lastModified": {"type": ["string", "null"]},
            },
        },
        "steps": {"type": "array", "items": _PROCESS_STEP},
        "transitions": {"type": "array", "items": _PROCESS_TRANSITION},
        "notes": {"type": "array", "items": _PROCESS_NOTE},
    },
}

# A FigJam board is a tree, and a malformed or hostile one could be arbitrarily
# deep. Recursion is bounded rather than trusted; anything below the limit is
# dropped, which loses content but cannot exhaust the stack.
MAX_TREE_DEPTH = 64
# What a rounded or diamond shape means in a flow chart. Everything else is a
# plain step -- FigJam offers dozens of shapes and guessing intent from each one
# would invent structure the author did not draw.
_SHAPE_KINDS = {"ELLIPSE": "terminal", "ROUNDED_RECTANGLE": "terminal", "DIAMOND": "decision"}


def _schema(properties: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "required": list(required),
    }


# The manifest this adapter serves, written out rather than derived from the
# registry. The duplication is the control: the registry hashes what it reads here
# and refuses the read when the two drift apart.
_TOOL_MANIFEST = (
    RemoteToolDescription(
        name="getFigmaFile",
        input_schema=_schema({"fileKey": _FILE_KEY, "depth": _DEPTH}, ("fileKey",)),
    ),
    RemoteToolDescription(
        name="getFigmaNode",
        input_schema=_schema(
            {"fileKey": _FILE_KEY, "nodeId": _NODE_ID, "depth": _DEPTH},
            ("fileKey", "nodeId"),
        ),
    ),
    RemoteToolDescription(
        name="renderFigmaNode",
        input_schema=_schema(
            {"fileKey": _FILE_KEY, "nodeId": _NODE_ID, "scale": _SCALE},
            ("fileKey", "nodeId"),
        ),
    ),
    RemoteToolDescription(
        name="extractFigmaProcess",
        input_schema=_schema({"fileKey": _FILE_KEY, "nodeId": _NODE_ID}, ("fileKey",)),
        output_schema=_PROCESS_SCHEMA,
    ),
)


def _shape_text(node: Mapping[str, Any]) -> str:
    """The text a FigJam shape carries, wherever the API chose to put it."""

    characters = node.get("characters")
    if isinstance(characters, str) and characters.strip():
        return characters.strip()
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, Mapping):
                nested = _shape_text(child)
                if nested:
                    return nested
    return ""


def _endpoint_id(endpoint: Any) -> str | None:
    """The shape a connector end is attached to, or None when it dangles."""

    if isinstance(endpoint, Mapping):
        node_id = endpoint.get("endpointNodeId")
        if isinstance(node_id, str) and node_id:
            return node_id
    return None


def _collect(
    node: Any,
    section: str | None,
    depth: int,
    shapes: list[tuple[Mapping[str, Any], str | None]],
    connectors: list[Mapping[str, Any]],
    notes: list[tuple[Mapping[str, Any], str | None]],
) -> None:
    if depth > MAX_TREE_DEPTH or not isinstance(node, Mapping):
        return
    node_type = node.get("type")
    if node_type == "SECTION":
        name = node.get("name")
        section = name if isinstance(name, str) and name else section
    elif node_type == "SHAPE_WITH_TEXT":
        shapes.append((node, section))
    elif node_type == "CONNECTOR":
        connectors.append(node)
    elif node_type == "STICKY":
        notes.append((node, section))
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            _collect(child, section, depth + 1, shapes, connectors, notes)


def _build_process(
    *,
    file_key: str,
    payload: Mapping[str, Any],
    roots: list[Any],
) -> dict[str, Any]:
    shapes: list[tuple[Mapping[str, Any], str | None]] = []
    connectors: list[Mapping[str, Any]] = []
    sticky_notes: list[tuple[Mapping[str, Any], str | None]] = []
    for root in roots:
        _collect(root, None, 0, shapes, connectors, sticky_notes)

    transitions: list[dict[str, Any]] = []
    incoming: set[str] = set()
    outgoing: set[str] = set()
    for connector in connectors:
        source = _endpoint_id(connector.get("connectorStart"))
        target = _endpoint_id(connector.get("connectorEnd"))
        if source is not None:
            outgoing.add(source)
        if target is not None:
            incoming.add(target)
        label = _shape_text(connector)
        transitions.append(
            {
                "id": str(connector.get("id", "")),
                "from": source,
                "to": target,
                "condition": label or None,
            }
        )

    steps: list[dict[str, Any]] = []
    for shape, section in shapes:
        shape_id = str(shape.get("id", ""))
        shape_type = shape.get("shapeType")
        kind = _SHAPE_KINDS.get(shape_type, "step") if isinstance(shape_type, str) else "step"
        if kind == "terminal":
            # An entry point is a terminal nothing arrives at; an exit is one
            # nothing leaves. A shape that is both, or neither, stays "terminal"
            # rather than being assigned a role the diagram does not support.
            has_in = shape_id in incoming
            has_out = shape_id in outgoing
            if has_out and not has_in:
                kind = "start"
            elif has_in and not has_out:
                kind = "end"
        step: dict[str, Any] = {
            "id": shape_id,
            "label": _shape_text(shape),
            "kind": kind,
            "section": section,
        }
        if isinstance(shape_type, str):
            step["shape"] = shape_type
        steps.append(step)

    name = payload.get("name")
    last_modified = payload.get("lastModified")
    return {
        "file": {
            "key": file_key,
            "name": name if isinstance(name, str) else "",
            "lastModified": last_modified if isinstance(last_modified, str) else None,
        },
        "steps": steps,
        "transitions": transitions,
        "notes": [
            {
                "id": str(note.get("id", "")),
                "text": _shape_text(note),
                "section": section,
            }
            for note, section in sticky_notes
        ],
    }


def _api_node_id(node_id: str) -> str:
    """Figma writes a node id with a colon in its API and a hyphen in shared links."""

    return node_id.replace("-", ":", 1)


class FigmaRESTSession:
    """One authenticated conversation with the Figma REST API.

    Presents the MCP read-session shape so the workflow above it -- allowlist,
    schema check, size limits, provenance, audit -- runs identically whether the
    bytes came from an MCP server or from here.
    """

    def __init__(self, *, client: httpx2.AsyncClient) -> None:
        self._client = client

    @property
    def protocol_version(self) -> str:
        return FIGMA_REST_PROTOCOL_VERSION

    async def list_tools(self) -> tuple[RemoteToolDescription, ...]:
        return _TOOL_MANIFEST

    async def call_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> RemoteToolResult:
        if tool_name == "extractFigmaProcess":
            # The only tool whose result is derived rather than forwarded, so the
            # only one returning structured content: the shape is ours, declared in
            # the contract, and validated by the workflow before it reaches a caller.
            return RemoteToolResult(
                content=(),
                structured_content=await self._extract_process(arguments),
            )
        if tool_name == "getFigmaFile":
            payload = await self._get_file(arguments)
        elif tool_name == "getFigmaNode":
            payload = await self._get_node(arguments)
        elif tool_name == "renderFigmaNode":
            payload = await self._render_node(arguments)
        else:  # pragma: no cover - the registry allowlist runs first
            raise MCPToolDenied()

        # Returned as a text block with no structured content: the contracts declare
        # no provider output schema, and the workflow refuses structured content that
        # nothing authenticates. The body stays verbatim so its hash in the audit
        # trail refers to what Figma actually sent.
        return RemoteToolResult(
            content=(
                RemoteContentBlock(
                    kind="text",
                    text=json.dumps(payload, ensure_ascii=False, allow_nan=False),
                ),
            ),
            structured_content=None,
        )

    async def _get_file(self, arguments: dict[str, Any]) -> Any:
        file_key = quote(str(arguments["fileKey"]), safe="")
        params: dict[str, Any] = {}
        if "depth" in arguments:
            params["depth"] = arguments["depth"]
        return await self._get(f"/v1/files/{file_key}", params)

    async def _get_node(self, arguments: dict[str, Any]) -> Any:
        file_key = quote(str(arguments["fileKey"]), safe="")
        params: dict[str, Any] = {"ids": _api_node_id(str(arguments["nodeId"]))}
        if "depth" in arguments:
            params["depth"] = arguments["depth"]
        return await self._get(f"/v1/files/{file_key}/nodes", params)

    async def _render_node(self, arguments: dict[str, Any]) -> Any:
        file_key = quote(str(arguments["fileKey"]), safe="")
        params: dict[str, Any] = {
            "ids": _api_node_id(str(arguments["nodeId"])),
            "format": "png",
        }
        if "scale" in arguments:
            params["scale"] = arguments["scale"]
        # Figma answers with a short-lived URL on its own CDN rather than with image
        # bytes. That URL is returned as data and deliberately not followed: fetching
        # a destination named by a response is the shape this transport exists to
        # refuse. Rendering it is the caller's decision, made outside this boundary.
        return await self._get(f"/v1/images/{file_key}", params)

    async def _extract_process(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Turn a FigJam board into steps and transitions.

        A whole file is read when no node is named, because a process is rarely
        one node: sections group it, and the connectors that carry the graph are
        siblings of the shapes they join.
        """

        file_key = str(arguments["fileKey"])
        if "nodeId" in arguments:
            payload = await self._get_node(arguments)
            nodes = payload.get("nodes") if isinstance(payload, dict) else None
            roots = [
                entry["document"]
                for entry in (nodes or {}).values()
                if isinstance(entry, dict) and isinstance(entry.get("document"), dict)
            ]
        else:
            payload = await self._get_file({"fileKey": file_key})
            document = payload.get("document") if isinstance(payload, dict) else None
            roots = [document] if isinstance(document, dict) else []
        if not isinstance(payload, dict):
            raise MCPInvalidResponse()
        return _build_process(file_key=file_key, payload=payload, roots=roots)

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            with anyio.fail_after(CALL_TIMEOUT_SECONDS):
                response = await self._client.get(path, params=params)
        except TimeoutError as error:
            raise MCPCallTimeout() from error
        except httpx2.TimeoutException as error:
            raise MCPCallTimeout() from error
        except httpx2.HTTPError as error:
            raise MCPTransportFailure() from error

        if response.status_code in {401, 403}:
            # The delegated credential is rejected or no longer covers this file.
            # Reported as a grant problem so the operator looks at the token rather
            # than at the network, which is where a transport failure would send them.
            raise MCPGrantUnavailable()
        if response.status_code == 429:
            # A quota is not an outage, and filing it under a transport failure sends
            # the operator hunting a network problem that does not exist. Figma prices
            # its endpoints by cost and a whole-file read is the dearest of them, so
            # this can mean days rather than seconds -- the delay is logged because it
            # is the only actionable part, and it carries nothing sensitive.
            retry_after = response.headers.get("retry-after")
            logger.warning(
                "Figma is rate limiting this credential",
                extra={"mcp_provider": "figma", "retry_after": retry_after},
            )
            raise MCPRateLimited()
        if response.status_code == 408 or response.status_code >= 500:
            raise MCPTransportFailure()
        if response.status_code != 200:
            raise MCPRemoteToolFailure()

        try:
            return response.json()
        except ValueError as error:
            raise MCPInvalidResponse() from error


class FigmaRESTTransport:
    """Read-only Figma transport. Credentials never leave this adapter."""

    def __init__(
        self,
        *,
        grant_broker: DelegatedGrantBroker,
        credential_kind: FigmaCredentialKind = "personal_access_token",
        resolver: EndpointResolver | None = None,
    ) -> None:
        self._grant_broker = grant_broker
        self._credential_kind = credential_kind
        self._resolver = resolver or SystemEndpointResolver()

    @asynccontextmanager
    async def connect(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> AsyncIterator[MCPReadSession]:
        if provider != MCPProvider.FIGMA:  # pragma: no cover - routed by provider
            raise MCPTransportFailure()

        hostname = urlsplit(FIGMA_REST_ENDPOINT).hostname
        if hostname is None:  # pragma: no cover - the endpoint is checked at import
            raise MCPDNSRejected()
        try:
            addresses = await self._resolver.resolve(hostname=hostname, port=HTTPS_PORT)
        except Exception as error:
            raise MCPDNSRejected() from error
        if not addresses or any(
            not is_approved_public_address(address) for address in addresses
        ):
            raise MCPDNSRejected()

        grant = await self._grant_broker.acquire(
            provider=provider, binding=binding, context=context
        )
        # Figma authenticates a personal access token and an OAuth token by different
        # headers, and sending both would leave which one it honours to the server.
        # Exactly one is set, chosen by configuration.
        if self._credential_kind == "personal_access_token":
            credential_header = {"X-Figma-Token": grant.access_token}
        else:
            credential_header = {"Authorization": f"Bearer {grant.access_token}"}

        timeout = httpx2.Timeout(
            CALL_TIMEOUT_SECONDS,
            connect=CONNECT_TIMEOUT_SECONDS,
            read=CALL_TIMEOUT_SECONDS,
            write=CALL_TIMEOUT_SECONDS,
            pool=CONNECT_TIMEOUT_SECONDS,
        )
        client = httpx2.AsyncClient(
            base_url=FIGMA_REST_ENDPOINT,
            headers={"Accept-Encoding": "identity", **credential_header},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"response": [reject_oversized_response]},
        )
        async with client:
            yield FigmaRESTSession(client=client)
