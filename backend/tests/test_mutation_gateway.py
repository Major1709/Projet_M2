"""Le transport d'une ecriture approuvee.

Le sujet central de ce fichier est la distinction entre LEVER et RENDRE UN ECHEC,
parce qu'elle ne dit pas la meme chose a la reservation d'idempotence :

- rendre un echec signifie "l'ecriture n'a pas eu lieu, et je le sais" ; l'approbation
  se ferme sur cette issue ;
- lever signifie "j'ignore ou en est cette ecriture" ; la reservation reste ouverte et
  la reprise honnete represente la MEME cle.

Se tromper de sens n'est pas une question de style : rendre un echec sur un appel
interrompu declarerait qu'aucun ticket n'a ete cree, alors qu'il a peut-etre ete cree.
"""

from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.core.config import Settings
from app.core.identity import SecurityContext
from app.mcp.adapters.mutation_gateway import (
    ACTION_MISMATCH,
    BINDING_UNAVAILABLE,
    CONTRACT_UNKNOWN,
    INPUT_REJECTED,
    PROTOCOL_REJECTED,
    SCHEMA_DRIFTED,
    MCPMutationGateway,
)
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.domain import MCPToolCall, ToolActionClass
from app.mcp.mutation_registry import MCPMutationRegistry

CLOUD = "a761589f-69b8-4373-9c30-7561c2d45a39"
CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")
VALID = {"projectKey": "KAN", "issueTypeName": "Bug", "summary": "Le courriel ne part pas"}


def settings_with(**changes: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "test",
        "mcp_atlassian_jira_cloud_id": CLOUD,
        "mcp_atlassian_confluence_cloud_id": CLOUD,
    }
    base.update(changes)
    return Settings(**base)


class FakeTool:
    def __init__(self, name: str, schema: dict[str, Any]) -> None:
        self.name = name
        self.input_schema = schema
        self.output_schema = None


class FakeRemoteResult:
    def __init__(self, *, is_error: bool = False, structured: Any = None) -> None:
        self.is_error = is_error
        self.structured_content = structured
        self.content = ()


class FakeSession:
    def __init__(
        self,
        *,
        tools: list[FakeTool],
        protocol_version: str = "2026-07-28",
        result: Any = None,
        raises: Exception | None = None,
    ) -> None:
        self.protocol_version = protocol_version
        self._tools = tools
        self._result = result or FakeRemoteResult(structured={"key": "KAN-42"})
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def list_tools(self):
        return tuple(self._tools)

    async def call_tool(self, *, tool_name: str, arguments: dict[str, Any]):
        self.calls.append({"tool_name": tool_name, "arguments": arguments})
        if self._raises is not None:
            raise self._raises
        return self._result


class FakeTransport:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    @asynccontextmanager
    async def connect(self, *, provider, binding, context):
        yield self.session


def a_session(**changes: Any) -> FakeSession:
    contract = MCPMutationRegistry().get(SourceSystem.JIRA, "createJiraIssue")
    assert contract is not None
    tools = [FakeTool("createJiraIssue", contract.provider_input_schema)]
    return FakeSession(tools=tools, **changes)


def gateway_for(session: FakeSession, settings: Settings | None = None) -> MCPMutationGateway:
    return MCPMutationGateway(
        settings=settings or settings_with(),
        transport=FakeTransport(session),
    )


def a_call(**changes: Any) -> MCPToolCall:
    base: dict[str, Any] = {
        "source_system": SourceSystem.JIRA,
        "tool_name": "createJiraIssue",
        "action_class": ToolActionClass.CREATE,
        "arguments": dict(VALID),
        "correlation_id": "corr-1",
    }
    base.update(changes)
    return MCPToolCall(**base)


def execute(gateway: MCPMutationGateway, call: MCPToolCall):
    return gateway.execute_mutation(call=call, context=CONTEXT, idempotency_key="cle-1")


def test_an_approved_write_reaches_the_provider() -> None:
    session = a_session()

    result = execute(gateway_for(session), a_call())

    assert result.succeeded is True
    assert result.external_ids == ("KAN-42",)
    assert session.calls[0]["tool_name"] == "createJiraIssue"


def test_the_binding_is_injected_and_never_taken_from_the_caller() -> None:
    """Injecte cote serveur apres l'approbation : c'est ce qui garantit qu'une ecriture
    approuvee ne peut pas atterrir sur un autre site."""

    session = a_session()

    execute(gateway_for(session), a_call())

    assert session.calls[0]["arguments"]["cloudId"] == CLOUD


def test_a_caller_supplied_binding_is_refused_by_the_public_schema() -> None:
    """Le schema public est ferme et ne declare pas cloudId, donc la tentative echoue
    a la premiere validation -- avant meme l'injection."""

    result = execute(gateway_for(a_session()), a_call(arguments={**VALID, "cloudId": "autre"}))

    assert result.succeeded is False
    assert result.error_code == INPUT_REJECTED


def test_a_field_the_approval_never_showed_is_refused() -> None:
    """``additional_fields`` est le seul moyen de fixer priorite, etiquettes et champs
    personnalises chez le fournisseur. Une proposition qui le porterait afficherait
    "creer un ticket intitule X" tout en pouvant ecrire ailleurs."""

    result = execute(
        gateway_for(a_session()),
        a_call(arguments={**VALID, "additional_fields": {"priority": {"name": "High"}}}),
    )

    assert result.succeeded is False
    assert result.error_code == INPUT_REJECTED


def test_an_undeclared_tool_is_refused_before_any_connection() -> None:
    session = a_session()

    result = execute(gateway_for(session), a_call(tool_name="deleteJiraProject"))

    assert result.error_code == CONTRACT_UNKNOWN
    assert session.calls == []


def test_an_action_class_that_does_not_match_the_contract_is_refused() -> None:
    """L'approbation portait sur une classe d'action. Un appel qui en presente une
    autre ne correspond plus a ce qui a ete montre a l'humain."""

    result = execute(gateway_for(a_session()), a_call(action_class=ToolActionClass.DELETE))

    assert result.error_code == ACTION_MISMATCH


def test_a_missing_binding_is_refused_rather_than_guessed() -> None:
    session = a_session()

    result = execute(
        gateway_for(session, settings_with(mcp_atlassian_jira_cloud_id=None)),
        a_call(),
    )

    assert result.error_code == BINDING_UNAVAILABLE
    assert session.calls == []


def test_schema_drift_is_rechecked_immediately_before_the_write() -> None:
    """Pas seulement a la proposition. Une approbation peut attendre quinze minutes ;
    le fournisseur a pu changer la forme de l'outil, et l'humain a approuve l'ancienne.
    """

    derive = a_session()
    derive._tools = [FakeTool("createJiraIssue", {"type": "object", "properties": {}})]

    result = execute(gateway_for(derive), a_call())

    assert result.error_code == SCHEMA_DRIFTED
    assert derive.calls == []


def test_an_unapproved_protocol_version_stops_the_write() -> None:
    result = execute(gateway_for(a_session(protocol_version="1999-01-01")), a_call())

    assert result.error_code == PROTOCOL_REJECTED


def test_a_provider_refusal_is_a_known_outcome() -> None:
    """Le fournisseur a repondu : l'ecriture n'a pas eu lieu et nous le savons."""

    session = a_session(result=FakeRemoteResult(is_error=True))

    result = execute(gateway_for(session), a_call())

    assert result.succeeded is False
    assert result.error_code == "MUTATION_PROVIDER_REFUSED"


def test_a_call_that_breaks_mid_flight_raises_instead_of_concluding() -> None:
    """La propriete la plus facile a casser sans s'en apercevoir.

    Rendre un echec ici declarerait qu'aucun ticket n'a ete cree, alors qu'il a
    peut-etre ete cree : la reservation se fermerait sur une contre-verite, et
    personne n'irait demander au fournisseur ce qu'il en a fait.
    """

    session = a_session(raises=ConnectionResetError("coupure en plein appel"))

    with pytest.raises(ConnectionResetError):
        execute(gateway_for(session), a_call())


def test_every_refusal_before_dispatch_is_returned_and_not_raised() -> None:
    """Le pendant : ces refus-la sont connus, donc l'approbation se ferme dessus au
    lieu de rester ouverte a une reprise qui echouerait a l'identique."""

    for call in (
        a_call(tool_name="inconnu"),
        a_call(action_class=ToolActionClass.DELETE),
        a_call(arguments={"projectKey": "minuscule"}),
    ):
        resultat = execute(gateway_for(a_session()), call)
        assert resultat.succeeded is False
        assert resultat.error_code is not None


def test_the_project_key_pattern_is_enforced_on_the_way_out() -> None:
    result = execute(gateway_for(a_session()), a_call(arguments={**VALID, "projectKey": "../x"}))

    assert result.error_code == INPUT_REJECTED


def test_a_result_without_an_identifier_still_succeeds() -> None:
    """Le fournisseur n'est pas oblige de nommer ce qu'il a cree, et son silence
    n'est pas un echec."""

    session = a_session(result=FakeRemoteResult(structured=None))

    result = execute(gateway_for(session), a_call())

    assert result.succeeded is True
    assert result.external_ids == ()
