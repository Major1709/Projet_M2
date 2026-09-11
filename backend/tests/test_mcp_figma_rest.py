import asyncio
import json
from typing import Any

import pytest

from app.core.identity import SecurityContext
from app.mcp.adapters import figma_rest
from app.mcp.adapters.figma_rest import (
    _TOOL_MANIFEST,
    MAX_TREE_DEPTH,
    FigmaRESTSession,
    FigmaRESTTransport,
)
from app.mcp.adapters.grants import BearerGrant
from app.mcp.adapters.routing import ProviderRoutedTransport
from app.mcp.domain import MCPBindingKind, MCPProvider
from app.mcp.errors import (
    MCPCallTimeout,
    MCPDNSRejected,
    MCPGrantUnavailable,
    MCPInvalidResponse,
    MCPRateLimited,
    MCPRemoteToolFailure,
    MCPTransportFailure,
)
from app.mcp.registry import (
    APPROVED_REMOTE_PROTOCOL_VERSIONS,
    FIGMA_REST_PROTOCOL_VERSION,
    MCPToolRegistry,
    schema_sha256,
)

CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        valid_json: bool = True,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {"name": "Processus"}
        self._valid_json = valid_json

    def json(self) -> Any:
        if not self._valid_json:
            raise ValueError("not json")
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response = response or FakeResponse()
        self.error = error
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, *, params: dict[str, Any]) -> FakeResponse:
        self.requests.append((path, params))
        if self.error is not None:
            raise self.error
        return self.response


class StubGrantBroker:
    def __init__(self, token: str = "synthetic-figma-token-0001") -> None:
        self.token = token
        self.calls: list[tuple[MCPProvider, MCPBindingKind]] = []

    async def acquire(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> BearerGrant:
        del context
        self.calls.append((provider, binding))
        return BearerGrant(
            provider=provider,
            binding=binding,
            tenant_id="tenant-a",
            user_id="user-a",
            access_token=self.token,
        )


class StubResolver:
    def __init__(self, addresses: tuple[str, ...] = ("93.184.216.34",)) -> None:
        self.addresses = addresses
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, *, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        return self.addresses


def call(session: FigmaRESTSession, tool_name: str, arguments: dict[str, Any]):
    return asyncio.run(session.call_tool(tool_name=tool_name, arguments=arguments))


def test_the_published_manifest_matches_every_registry_contract() -> None:
    """The drift check only means something if the two declarations are kept apart.

    Both sides are ours here, so this cannot catch a third party changing its
    contract. What it does catch is one of the two being edited alone, which would
    otherwise fail at runtime as an unexplained refused read.
    """
    contracts = {
        contract.tool_name: contract
        for contract in MCPToolRegistry().contracts
        if contract.provider == MCPProvider.FIGMA
    }

    assert set(contracts) == {tool.name for tool in _TOOL_MANIFEST}
    for tool in _TOOL_MANIFEST:
        contract = contracts[tool.name]
        assert schema_sha256(tool.input_schema) == contract.provider_input_schema_sha256
        if tool.output_schema is None:
            assert contract.provider_output_schema_sha256 is None
        else:
            assert schema_sha256(tool.output_schema) == contract.provider_output_schema_sha256

    # Only the derived tool declares an output schema. The passthrough tools return
    # whatever Figma sent, and pinning a shape to that would be a promise we cannot
    # keep on someone else's behalf.
    declared = {tool.name for tool in _TOOL_MANIFEST if tool.output_schema is not None}
    assert declared == {"extractFigmaProcess"}


def test_the_rest_protocol_marker_can_never_be_claimed_by_a_remote_server() -> None:
    assert FIGMA_REST_PROTOCOL_VERSION not in APPROVED_REMOTE_PROTOCOL_VERSIONS


def test_each_tool_maps_onto_its_read_only_rest_route() -> None:
    client = FakeClient()
    session = FigmaRESTSession(client=client)

    call(session, "getFigmaFile", {"fileKey": "abc123", "depth": 2})
    call(session, "getFigmaNode", {"fileKey": "abc123", "nodeId": "36:114"})
    call(session, "renderFigmaNode", {"fileKey": "abc123", "nodeId": "36:114", "scale": 2})

    assert client.requests == [
        ("/v1/files/abc123", {"depth": 2}),
        ("/v1/files/abc123/nodes", {"ids": "36:114"}),
        ("/v1/images/abc123", {"ids": "36:114", "format": "png", "scale": 2}),
    ]


def test_a_node_id_taken_from_a_shared_link_is_translated_for_the_api() -> None:
    """Figma writes a node id with a hyphen in a link and a colon in its API."""
    client = FakeClient()
    session = FigmaRESTSession(client=client)

    call(session, "getFigmaNode", {"fileKey": "abc123", "nodeId": "36-114"})

    assert client.requests == [("/v1/files/abc123/nodes", {"ids": "36:114"})]


def test_a_response_is_returned_verbatim_as_text_without_structured_content() -> None:
    payload = {"name": "Processus", "document": {"id": "0:0"}}
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    result = call(session, "getFigmaFile", {"fileKey": "abc123"})

    assert result.structured_content is None
    assert len(result.content) == 1
    assert json.loads(result.content[0].text or "") == payload


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, MCPGrantUnavailable),
        (403, MCPGrantUnavailable),
        (404, MCPRemoteToolFailure),
        (400, MCPRemoteToolFailure),
        (408, MCPTransportFailure),
        (429, MCPRateLimited),
        (500, MCPTransportFailure),
        (503, MCPTransportFailure),
    ],
)
def test_a_provider_status_maps_onto_the_error_taxonomy(
    status_code: int,
    expected: type[Exception],
) -> None:
    """A rejected credential must not be reported as a network problem.

    The distinction is operational, not cosmetic: MCP_GRANT_UNAVAILABLE sends the
    operator to the token, MCP_TRANSPORT_FAILURE sends them to the network, and
    the second is the wrong place to spend an afternoon.
    """
    session = FigmaRESTSession(client=FakeClient(FakeResponse(status_code=status_code)))

    with pytest.raises(expected):
        call(session, "getFigmaFile", {"fileKey": "abc123"})


def test_a_quota_refusal_logs_how_long_it_lasts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Figma prices a whole-file read dearly, so its Retry-After can be days.

    That delay is the only actionable part of a 429 and the response body carries
    nothing sensitive, so it is logged rather than discarded -- otherwise the
    operator sees a refusal with no way to tell a blip from a four-day lockout.
    """
    session = FigmaRESTSession(
        client=FakeClient(FakeResponse(status_code=429, headers={"retry-after": "396763"}))
    )

    with caplog.at_level("WARNING"), pytest.raises(MCPRateLimited):
        call(session, "getFigmaFile", {"fileKey": "abc1234567"})

    assert any(record.retry_after == "396763" for record in caplog.records)


def test_a_timeout_is_reported_as_a_timeout_not_as_a_transport_failure() -> None:
    session = FigmaRESTSession(client=FakeClient(error=figma_rest.httpx2.ConnectTimeout("slow")))

    with pytest.raises(MCPCallTimeout):
        call(session, "getFigmaFile", {"fileKey": "abc123"})


def test_a_body_that_is_not_json_is_refused() -> None:
    session = FigmaRESTSession(client=FakeClient(FakeResponse(valid_json=False)))

    with pytest.raises(MCPInvalidResponse):
        call(session, "getFigmaFile", {"fileKey": "abc123"})


@pytest.mark.parametrize(
    ("credential_kind", "expected_header", "unexpected_header"),
    [
        ("personal_access_token", "X-Figma-Token", "Authorization"),
        ("oauth", "Authorization", "X-Figma-Token"),
    ],
)
def test_exactly_one_credential_header_is_sent(
    monkeypatch: pytest.MonkeyPatch,
    credential_kind: str,
    expected_header: str,
    unexpected_header: str,
) -> None:
    captured: dict[str, Any] = {}

    class CapturingClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> "CapturingClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(figma_rest.httpx2, "AsyncClient", CapturingClient)
    broker = StubGrantBroker()
    transport = FigmaRESTTransport(
        grant_broker=broker,
        credential_kind=credential_kind,  # type: ignore[arg-type]
        resolver=StubResolver(),
    )

    async def connect_once() -> str:
        async with transport.connect(
            provider=MCPProvider.FIGMA,
            binding=MCPBindingKind.FIGMA,
            context=CONTEXT,
        ) as session:
            return session.protocol_version

    assert asyncio.run(connect_once()) == FIGMA_REST_PROTOCOL_VERSION
    headers = captured["headers"]
    assert expected_header in headers
    assert unexpected_header not in headers
    assert broker.token in headers[expected_header]
    assert captured["follow_redirects"] is False
    assert captured["trust_env"] is False


@pytest.mark.parametrize(
    "addresses",
    [("127.0.0.1",), ("169.254.169.254",), ("10.0.0.1",), ("8.8.8.8", "192.168.1.10"), ("::1",)],
)
def test_a_private_address_is_refused_before_the_credential_is_acquired(
    addresses: tuple[str, ...],
) -> None:
    """The REST endpoint is public, so this guard should never fire in practice.

    It is asserted anyway because a resolver answer is not under our control, and a
    credential handed out before the destination is approved is a credential sent
    to whatever answered.
    """
    broker = StubGrantBroker()
    transport = FigmaRESTTransport(
        grant_broker=broker,
        resolver=StubResolver(addresses),
    )

    async def connect_once() -> None:
        async with transport.connect(
            provider=MCPProvider.FIGMA,
            binding=MCPBindingKind.FIGMA,
            context=CONTEXT,
        ):
            raise AssertionError("A rejected address must not open a transport")

    with pytest.raises(MCPDNSRejected):
        asyncio.run(connect_once())

    assert broker.calls == []


def _board(*children: dict[str, Any]) -> dict[str, Any]:
    """A FigJam payload shaped like the one the real board returns."""

    return {
        "name": "PROCESS",
        "lastModified": "2026-08-15T05:42:17Z",
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "0:1",
                    "type": "CANVAS",
                    "name": "Page 1",
                    "children": [
                        {
                            "id": "1:2",
                            "type": "SECTION",
                            "name": "Section 1",
                            "children": list(children),
                        }
                    ],
                }
            ],
        },
    }


def _shape(node_id: str, text: str, shape_type: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "SHAPE_WITH_TEXT",
        "shapeType": shape_type,
        "characters": text,
    }


def _connector(node_id: str, source: str, target: str, label: str = "") -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "CONNECTOR",
        "characters": label,
        "connectorStart": {"endpointNodeId": source, "magnet": "RIGHT"},
        "connectorEnd": {"endpointNodeId": target, "magnet": "LEFT"},
    }


def test_a_board_becomes_steps_and_oriented_transitions() -> None:
    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        _shape("1:24", "se connecter", "SQUARE"),
        _shape("1:30", "compte valide ?", "DIAMOND"),
        _shape("1:40", "fin", "ELLIPSE"),
        _connector("1:25", "1:3", "1:24"),
        _connector("1:31", "1:24", "1:30"),
        _connector("1:32", "1:30", "1:40", label="oui"),
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    result = call(session, "extractFigmaProcess", {"fileKey": "vMpmSEiNsvBB8eu6n7SKZS"})
    process = result.structured_content

    assert result.content == ()
    assert process["file"] == {
        "key": "vMpmSEiNsvBB8eu6n7SKZS",
        "name": "PROCESS",
        "lastModified": "2026-08-15T05:42:17Z",
    }
    assert [(s["id"], s["label"], s["kind"], s["section"]) for s in process["steps"]] == [
        ("1:3", "start", "start", "Section 1"),
        ("1:24", "se connecter", "step", "Section 1"),
        ("1:30", "compte valide ?", "decision", "Section 1"),
        ("1:40", "fin", "end", "Section 1"),
    ]
    assert [(t["from"], t["to"], t["condition"]) for t in process["transitions"]] == [
        ("1:3", "1:24", None),
        ("1:24", "1:30", None),
        ("1:30", "1:40", "oui"),
    ]


def test_a_lone_rounded_shape_is_neither_a_start_nor_an_end() -> None:
    """Entry and exit are read from connectivity, so an isolated shape claims neither."""
    payload = _board(_shape("1:3", "orpheline", "ELLIPSE"))
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert process["steps"][0]["kind"] == "terminal"


def test_a_dangling_connector_is_reported_rather_than_dropped() -> None:
    """An arrow anchored to a coordinate means the diagram is incomplete.

    Discarding it would hand back a graph that looks whole, which is worse than a
    transition that openly says one of its ends is missing.
    """
    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        {
            "id": "1:25",
            "type": "CONNECTOR",
            "connectorStart": {"endpointNodeId": "1:3"},
            "connectorEnd": {"position": {"x": 10.0, "y": 20.0}},
        },
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert process["transitions"] == [{"id": "1:25", "from": "1:3", "to": None, "condition": None}]
    assert process["steps"][0]["kind"] == "start"


def test_sticky_notes_are_kept_apart_from_the_flow() -> None:
    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        {"id": "1:9", "type": "STICKY", "characters": "a valider avec le metier"},
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert len(process["steps"]) == 1
    assert process["notes"] == [
        {
            "id": "1:9",
            "text": "a valider avec le metier",
            "section": "Section 1",
            "origin": "sticky",
        }
    ]


def test_an_absurdly_deep_board_cannot_exhaust_the_stack() -> None:
    node: dict[str, Any] = _shape("1:3", "profond", "SQUARE")
    for index in range(MAX_TREE_DEPTH + 40):
        node = {"id": f"g:{index}", "type": "GROUP", "children": [node]}
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=_board(node))))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert process["steps"] == []


def test_an_unrouted_provider_fails_rather_than_falling_back() -> None:
    routed = ProviderRoutedTransport({})

    async def connect_once() -> None:
        async with routed.connect(
            provider=MCPProvider.FIGMA,
            binding=MCPBindingKind.FIGMA,
            context=CONTEXT,
        ):
            raise AssertionError("An unrouted provider must not open a transport")

    with pytest.raises(MCPTransportFailure):
        asyncio.run(connect_once())


# --- Distinguer la legende du flux reel ---------------------------------------------
#
# Sur le board Accesa, une zone explique la convention du diagramme : un START vide,
# un rectangle "Action / Traitement", un losange "Decision". Ces formes ne sont
# reliees a rien. Traitees comme des etapes, elles produisaient des lignes de backlog
# creuses -- "[Etape sans libelle]" -- indiscernables d'une specification reelle.
#
# Le signal est dans le dessin : une forme qu'aucune fleche ne touche ne fait pas
# partie du parcours.


def test_a_shape_no_arrow_touches_is_not_a_step() -> None:
    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        _shape("1:24", "se connecter", "SQUARE"),
        _connector("1:25", "1:3", "1:24"),
        # La legende, posee a cote du flux.
        _shape("1:80", "Action / Traitement", "SQUARE"),
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert [s["id"] for s in process["steps"]] == ["1:3", "1:24"]


def test_a_detached_shape_that_says_something_is_kept_as_a_note() -> None:
    """Une legende porte parfois la regle qui manque au flux. L'ecarter comme etape
    ne doit pas revenir a la jeter."""

    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        _shape("1:24", "se connecter", "SQUARE"),
        _connector("1:25", "1:3", "1:24"),
        _shape("1:88", "Si Android : empreinte. Si iOS : Face ID.", "SQUARE"),
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert process["notes"] == [
        {
            "id": "1:88",
            "text": "Si Android : empreinte. Si iOS : Face ID.",
            "section": "Section 1",
            "origin": "detached_shape",
        }
    ]


def test_a_board_without_any_arrow_keeps_all_its_shapes() -> None:
    """Sans fleche, rien ne distingue une legende d'une etape. Tout ecarter
    remplacerait du bruit par du vide."""

    payload = _board(
        _shape("1:3", "une etape", "SQUARE"),
        _shape("1:4", "une autre", "SQUARE"),
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert [s["id"] for s in process["steps"]] == ["1:3", "1:4"]


def test_a_shape_without_text_never_becomes_a_step() -> None:
    """Une forme muette ne porte aucune exigence. La garder produisait du
    remplissage qui avait l'air d'une specification."""

    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        _shape("1:24", "", "SQUARE"),
        _shape("1:30", "fin", "ELLIPSE"),
        _connector("1:25", "1:3", "1:24"),
        _connector("1:26", "1:24", "1:30"),
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert [s["id"] for s in process["steps"]] == ["1:3", "1:30"]
    # L'enchainement reste lisible : la forme muette garde sa place dans les
    # transitions, donc le chemin n'est pas coupe.
    assert [(t["from"], t["to"]) for t in process["transitions"]] == [
        ("1:3", "1:24"),
        ("1:24", "1:30"),
    ]


def test_a_free_text_block_becomes_a_note() -> None:
    """Sur un board reel, la regle conditionnelle la plus utile du tableau etait
    dans un bloc de texte libre, que l'extraction ignorait."""

    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        {
            "id": "1:88",
            "type": "TEXT",
            "characters": "REMARQUE Si Android : empreinte. Si iOS : Face ID.",
        },
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert [(n["text"], n["origin"]) for n in process["notes"]] == [
        ("REMARQUE Si Android : empreinte. Si iOS : Face ID.", "text")
    ]


def test_an_empty_text_block_adds_no_note() -> None:
    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        {"id": "1:67", "type": "TEXT", "characters": "   "},
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert process["notes"] == []


def test_a_note_reduced_to_a_stray_character_is_not_kept() -> None:
    """Deux zones de texte du board reel se reduisaient a un guillemet orphelin et a
    un caractere de police privee. Une remarque vide dans un cahier des charges
    ressemble a une information perdue."""

    payload = _board(
        _shape("1:3", "start", "ELLIPSE"),
        {"id": "1:81", "type": "TEXT", "characters": "\u201d"},
        {"id": "1:67", "type": "TEXT", "characters": "\ue2ff"},
        {"id": "1:88", "type": "TEXT", "characters": "Si iOS : Face ID"},
    )
    session = FigmaRESTSession(client=FakeClient(FakeResponse(payload=payload)))

    process = call(session, "extractFigmaProcess", {"fileKey": "abc1234567"}).structured_content

    assert [n["id"] for n in process["notes"]] == ["1:88"]
