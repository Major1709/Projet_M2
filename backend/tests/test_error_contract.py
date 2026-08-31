"""The API's failure contract, held to what the routes actually do.

A published contract that drifts from the behaviour is worse than none, because a
client trusts it. So these tests do not check that documentation exists -- they
check that it agrees with the code that produces the responses.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent.api import STATUS_BY_ERROR as AGENT_STATUS
from app.agent.api import translate_llm_error
from app.approvals.api import STATUS_BY_ERROR as APPROVAL_STATUS
from app.approvals.api import translate_domain_error
from app.approvals.errors import (
    InvalidTransition,
    ProposalExpired,
    ProposalNotFound,
    VersionConflict,
)
from app.core.config import Settings
from app.core.errors import ErrorResponse, responses_for
from app.main import create_app
from app.mcp.api import STATUS_BY_ERROR as MCP_STATUS
from app.mcp.api import translate_read_error

# Routes that answer without deriving an identity, so they have no failure to
# declare beyond what FastAPI generates.
UNGUARDED = {"/health", "/health/live", "/health/ready", "/api/auth/atlassian/signout"}


@pytest.fixture
def openapi() -> dict:
    return create_app(Settings(environment="test")).openapi()


def test_every_guarded_route_documents_how_it_can_fail(openapi: dict) -> None:
    """The gap this whole contract exists to close: routes that declared only 422."""

    undocumented = []
    for path, operations in openapi["paths"].items():
        if path in UNGUARDED:
            continue
        for method, operation in operations.items():
            declared = {int(code) for code in operation["responses"] if code.isdigit()}
            if not {code for code in declared if code >= 400 and code != 422}:
                undocumented.append(f"{method.upper()} {path}")
    assert undocumented == []


def test_every_documented_failure_carries_the_shared_envelope(openapi: dict) -> None:
    """One shape everywhere, so a client writes one error handler and not five."""

    expected = f"#/components/schemas/{ErrorResponse.__name__}"
    for path, operations in openapi["paths"].items():
        for method, operation in operations.items():
            for code, response in operation["responses"].items():
                if not code.isdigit() or int(code) < 400 or code == "422":
                    continue
                schema = response.get("content", {}).get("application/json", {})
                assert schema.get("schema", {}).get("$ref") == expected, (
                    f"{method.upper()} {path} -> {code}"
                )


@pytest.mark.parametrize(
    ("table", "translate", "sample"),
    [
        (APPROVAL_STATUS, translate_domain_error, {ProposalNotFound: (uuid4(),)}),
        (MCP_STATUS, translate_read_error, {}),
        (AGENT_STATUS, translate_llm_error, {}),
    ],
)
def test_the_documented_status_is_the_one_the_translator_returns(
    table: tuple, translate, sample: dict
) -> None:
    """The tables drive both the docs and the runtime, and this proves it stays so.

    Constructed and translated for real rather than compared as data: a table that
    matched itself would pass while the chain reading it did something else.
    """

    for error_type, documented in table:
        if error_type is VersionConflict:
            error = VersionConflict(expected=1, actual=2)
        else:
            error = error_type(*sample.get(error_type, ()))
        assert translate(error).status_code == documented, error_type.__name__


def test_a_failure_names_a_code_a_client_can_branch_on() -> None:
    """Not a sentence. Wording gets improved and translated; codes do not."""

    for error, code in (
        (ProposalNotFound(uuid4()), "PROPOSAL_NOT_FOUND"),
        (ProposalExpired("gone"), "PROPOSAL_EXPIRED"),
        (InvalidTransition("no"), "INVALID_TRANSITION"),
        (VersionConflict(expected=1, actual=2), "VERSION_CONFLICT"),
    ):
        detail = translate_domain_error(error).detail
        assert detail["code"] == code
        assert detail["message"]


def test_an_unauthenticated_call_is_refused_with_the_same_envelope() -> None:
    """End to end, through the app, so the shape is not merely declared."""

    app = create_app(Settings(environment="test", auth_mode="session"))
    response = TestClient(app).post(
        "/api/mcp/reads",
        json={"calls": [{"source_system": "jira", "tool_name": "getVisibleJiraProjects"}]},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "IDENTITY_REQUIRED"


def test_responses_for_groups_the_codes_that_share_a_status() -> None:
    """A client branching on 409 needs to know which codes arrive there."""

    built = responses_for(
        ((InvalidTransition, 409), (VersionConflict, 409), (ProposalExpired, 410))
    )

    assert built[409]["description"] == "INVALID_TRANSITION, VERSION_CONFLICT"
    assert built[410]["description"] == "PROPOSAL_EXPIRED"
