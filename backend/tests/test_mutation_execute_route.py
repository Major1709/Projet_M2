"""La route qui depense une approbation.

Deux proprietes valent le fichier a elles seules. La version attendue, sans laquelle
un second clic depenserait une approbation qui n'est plus celle qui a ete montree. Et
le 502 sur issue inconnue, qui doit rester distinct d'un echec : un client qui les
confondrait reessaierait et creerait le doublon que la reservation d'idempotence
existe pour eviter.
"""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.approvals.errors import ProposalExpired, ProposalNotFound, VersionConflict
from app.bootstrap import build_container
from app.core.config import Settings
from app.main import create_app
from app.mcp.domain import MCPExecutionResult

OWNER = {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"}
PROPOSAL = uuid4()


class StubRunner:
    """Enregistre ce qu'on lui a demande, ou leve ce qu'on lui a dit de lever."""

    def __init__(self, *, result: Any = None, error: Exception | None = None) -> None:
        self.result = result or MCPExecutionResult(succeeded=True, external_ids=("KAN-42",))
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def execute(self, *, proposal_id, expected_version, context):
        self.calls.append(
            {
                "proposal_id": proposal_id,
                "expected_version": expected_version,
                "tenant_id": context.tenant_id,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


def client_for(runner: StubRunner | None, **reglages: Any) -> TestClient:
    # Le conteneur est gele, donc remplace plutot que modifie -- ce qui est aussi la
    # facon dont il est construit en production : une seule fois, entierement.
    settings = Settings(environment="test", **reglages)
    container = replace(build_container(settings), mutations=runner)
    return TestClient(create_app(settings, container))


def execute(client: TestClient, *, version: int = 1, headers=OWNER):
    return client.post(
        f"/api/actions/{PROPOSAL}/execute",
        headers=headers,
        json={"expected_version": version},
    )


def test_an_approved_write_returns_what_the_provider_created() -> None:
    runner = StubRunner()

    response = execute(client_for(runner))

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] is True
    assert body["external_ids"] == ["KAN-42"]
    assert runner.calls[0]["expected_version"] == 1


def test_the_expected_version_travels_to_the_runner() -> None:
    """Entre l'affichage d'une proposition et le clic, elle a pu etre revisee, rejetee
    ou deja executee."""

    runner = StubRunner()

    execute(client_for(runner), version=7)

    assert runner.calls[0]["expected_version"] == 7


def test_a_stale_version_is_a_conflict_and_not_a_success() -> None:
    runner = StubRunner(error=VersionConflict(expected=1, actual=2))

    response = execute(client_for(runner))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VERSION_CONFLICT"


def test_an_expired_proposal_is_gone_rather_than_conflicting() -> None:
    """410 et non 409 : la fenetre est passee, donc reessayer cette proposition
    n'aboutira jamais."""

    runner = StubRunner(error=ProposalExpired("la fenetre est passee"))

    response = execute(client_for(runner))

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "PROPOSAL_EXPIRED"


def test_an_unknown_proposal_is_not_found() -> None:
    runner = StubRunner(error=ProposalNotFound(PROPOSAL))

    response = execute(client_for(runner))

    assert response.status_code == 404


def test_a_dispatched_call_with_no_answer_is_reported_as_unknown() -> None:
    """La propriete la plus importante du fichier.

    L'appel est parti et rien n'est revenu : le ticket a peut-etre ete cree. Un 500
    laisserait un client conclure a l'echec et reessayer, ce qui creerait le doublon
    que la reservation d'idempotence existe pour eviter.
    """

    runner = StubRunner(error=ConnectionResetError("coupure en plein appel"))

    response = execute(client_for(runner))

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "MUTATION_OUTCOME_UNKNOWN"
    # Le message dit au client quoi NE PAS faire, ce qui est la seule chose utile ici.
    assert "do not retry" in detail["message"].lower()


def test_a_known_refusal_is_a_two_hundred_carrying_a_failure() -> None:
    """Distinct du 502 : le fournisseur a repondu, l'ecriture n'a pas eu lieu, et cela
    se sait. Le code HTTP dit que l'echange a abouti ; le corps dit l'issue."""

    runner = StubRunner(
        result=MCPExecutionResult(
            succeeded=False,
            error_code="MUTATION_PROVIDER_REFUSED",
            safe_message="The source system refused this write",
        )
    )

    response = execute(client_for(runner))

    assert response.status_code == 200
    assert response.json()["succeeded"] is False
    assert response.json()["error_code"] == "MUTATION_PROVIDER_REFUSED"


def test_a_deployment_without_writes_refuses_as_policy() -> None:
    """403 et non 404, comme la route d'assistant sans modele : une surface
    desactivee est une decision de deploiement, annoncee franchement."""

    response = execute(client_for(None))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "MCP_MUTATIONS_DISABLED"


def test_an_unauthenticated_call_never_reaches_the_runner() -> None:
    """En mode session, et non dans le mode en-tetes de developpement : celui-ci
    accepte une identite sans preuve, ce qui est son role, et ne dit donc rien sur
    ce que fait le mode reel."""

    runner = StubRunner()

    response = execute(client_for(runner, auth_mode="session"), headers={})

    assert response.status_code == 401
    assert runner.calls == []


@pytest.mark.parametrize("corps", [{}, {"expected_version": -1}, {"expected_version": "un"}])
def test_a_malformed_body_is_refused_before_the_runner(corps: dict) -> None:
    runner = StubRunner()
    client = client_for(runner)

    response = client.post(f"/api/actions/{PROPOSAL}/execute", headers=OWNER, json=corps)

    assert response.status_code == 422
    assert runner.calls == []


def test_an_unexpected_field_is_refused() -> None:
    """Le modele est ferme : un client qui enverrait la cle d'idempotence, ou le nom
    de l'outil, doit l'apprendre plutot que de croire que le serveur l'a pris en
    compte."""

    runner = StubRunner()
    client = client_for(runner)

    response = client.post(
        f"/api/actions/{PROPOSAL}/execute",
        headers=OWNER,
        json={"expected_version": 1, "idempotency_key": "la-mienne"},
    )

    assert response.status_code == 422
    assert runner.calls == []
