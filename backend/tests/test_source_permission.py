"""Revalidation of a write's target, against the shapes the sources really return.

The fixtures below are not invented. They mirror responses captured on 2026-08-31
from the live deployment through the ordinary read pipeline, trimmed to the fields
that matter and with the author account ids replaced. Pinning the extractors
against them is the point: a version path that silently stops matching would make
every check pass on ``None == None``, which is the quiet way this control dies.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.core.identity import SecurityContext
from app.mcp.adapters.permission import (
    CHANGED,
    UNREADABLE,
    UNSUPPORTED,
    SourceReadPermissionVerifier,
    source_version_of,
)
from app.mcp.domain import (
    MCPProvider,
    MCPReadContent,
    MCPReadProvenance,
    MCPReadResult,
    MCPReadSourceSystem,
    MCPToolCall,
    PermissionCheck,
    SourceSystem,
    ToolActionClass,
)
from app.mcp.errors import MCPRemoteToolFailure

CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")

# getConfluencePage(pageId=98483, contentFormat=markdown). Note ``body``: a string,
# not an object -- the shape a reader would guess wrong.
CONFLUENCE_PAGE: dict[str, Any] = {
    "id": "98483",
    "title": "Modele : documentation de decision",
    "spaceId": 98309,
    "status": "current",
    "parentId": "98421",
    "body": "Contexte\n\nDecision\n",
    "version": {
        "number": 1,
        "message": "",
        "minorEdit": False,
        "authorId": "account-id",
        "createdAt": "2026-08-09T17:34:49.462Z",
        "ncsStepVersion": None,
    },
}

# getJiraIssue(issueIdOrKey=KAN-2).
JIRA_ISSUE: dict[str, Any] = {
    "id": "10001",
    "key": "KAN-2",
    "fields": {
        "summary": "Connexion",
        "created": "2026-08-19T20:24:40.876+0300",
        "updated": "2026-08-19T20:24:41.681+0300",
    },
}

CONFLUENCE_SPACES: dict[str, Any] = {
    "results": [
        {"id": "98309", "key": "DL", "name": "Developpement logiciel"},
        {"id": "196610", "key": "~71202001", "name": "Fanny Andrianaly"},
    ]
}

JIRA_PROJECTS: dict[str, Any] = {
    "values": [{"id": "10000", "key": "KAN", "name": "My Software Team"}],
    "total": 1,
}


def _result(payload: Any) -> MCPReadResult:
    text = json.dumps(payload)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return MCPReadResult(
        content=(
            MCPReadContent(
                kind="text",
                size_bytes=len(text.encode("utf-8")),
                sha256=digest,
                text=text,
            ),
        ),
        provenance=MCPReadProvenance(
            provider=MCPProvider.ATLASSIAN,
            source_system=MCPReadSourceSystem.CONFLUENCE,
            server_id="atlassian-rovo",
            source_origin="https://andrianalyfanny.atlassian.net",
            tool_name="getConfluencePage",
            protocol_version="2025-06-18",
            input_schema_sha256="0" * 64,
            arguments_sha256="1" * 64,
            binding_fingerprint="2" * 64,
            policy_version="1",
            correlation_id="permission-check",
            retrieved_at=datetime.now(UTC),
        ),
    )


class StubReads:
    """Stands in for MCPReadWorkflow, answering with a payload or raising."""

    def __init__(self, payload: Any = None, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[Any] = []

    async def execute_call(self, *, call: Any, context: Any) -> MCPReadResult:
        del context
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return _result(self.payload)


def check_for(
    source_system: SourceSystem,
    *,
    action_class: ToolActionClass = ToolActionClass.UPDATE,
    resource_id: str | None = "98483",
    expected_version: str | None = "1",
    container_id: str | None = None,
) -> PermissionCheck:
    return PermissionCheck(
        context=CONTEXT,
        call=MCPToolCall(
            source_system=source_system,
            tool_name="confluence.update_page",
            action_class=action_class,
            arguments={"body": "Corps revu"},
            correlation_id="corr-1",
        ),
        resource_type="page",
        resource_id=resource_id,
        expected_resource_version=expected_version,
        container_id=container_id,
    )


def test_the_confluence_version_is_read_where_confluence_actually_puts_it() -> None:
    assert source_version_of(SourceSystem.CONFLUENCE, CONFLUENCE_PAGE) == "1"


def test_the_jira_version_is_read_where_jira_actually_puts_it() -> None:
    assert (
        source_version_of(SourceSystem.JIRA, JIRA_ISSUE)
        == "2026-08-19T20:24:41.681+0300"
    )


def test_a_confluence_body_is_a_string_not_an_object() -> None:
    """A regression guard on the observed shape, because the obvious guess is wrong."""

    assert isinstance(CONFLUENCE_PAGE["body"], str)


def test_a_target_still_at_its_approved_version_is_allowed() -> None:
    verifier = SourceReadPermissionVerifier(reads=StubReads(CONFLUENCE_PAGE))

    decision = verifier.check(check_for(SourceSystem.CONFLUENCE))

    assert decision.allowed is True


def test_a_target_that_moved_since_the_approval_is_refused() -> None:
    """Someone edited the page between the human deciding and the write leaving."""

    verifier = SourceReadPermissionVerifier(reads=StubReads(CONFLUENCE_PAGE))

    decision = verifier.check(
        check_for(SourceSystem.CONFLUENCE, expected_version="7")
    )

    assert decision.allowed is False
    assert decision.reason_code == CHANGED


def test_a_jira_issue_is_revalidated_by_its_updated_timestamp() -> None:
    verifier = SourceReadPermissionVerifier(reads=StubReads(JIRA_ISSUE))

    allowed = verifier.check(
        check_for(
            SourceSystem.JIRA,
            resource_id="KAN-2",
            expected_version="2026-08-19T20:24:41.681+0300",
        )
    )
    stale = verifier.check(
        check_for(
            SourceSystem.JIRA,
            resource_id="KAN-2",
            expected_version="2026-08-19T20:00:00.000+0300",
        )
    )

    assert allowed.allowed is True
    assert stale.reason_code == CHANGED


def test_a_target_the_source_will_not_return_is_refused() -> None:
    """Gone and invisible answer alike: telling them apart confirms a resource
    exists to someone who cannot see it."""

    verifier = SourceReadPermissionVerifier(
        reads=StubReads(error=MCPRemoteToolFailure())
    )

    decision = verifier.check(check_for(SourceSystem.CONFLUENCE))

    assert decision.allowed is False
    assert decision.reason_code == UNREADABLE


def test_a_resource_that_states_no_version_is_refused_rather_than_waved_through() -> None:
    """"We could not tell" must never mean "go ahead"."""

    verifier = SourceReadPermissionVerifier(reads=StubReads({"id": "98483"}))

    decision = verifier.check(check_for(SourceSystem.CONFLUENCE))

    assert decision.allowed is False
    assert decision.reason_code == UNSUPPORTED


def test_a_creation_is_confirmed_against_the_visible_containers() -> None:
    verifier = SourceReadPermissionVerifier(reads=StubReads(CONFLUENCE_SPACES))

    decision = verifier.check(
        check_for(
            SourceSystem.CONFLUENCE,
            action_class=ToolActionClass.CREATE,
            resource_id=None,
            expected_version=None,
            container_id="98309",
        )
    )

    assert decision.allowed is True


def test_a_creation_into_a_container_the_credential_cannot_see_is_refused() -> None:
    verifier = SourceReadPermissionVerifier(reads=StubReads(CONFLUENCE_SPACES))

    decision = verifier.check(
        check_for(
            SourceSystem.CONFLUENCE,
            action_class=ToolActionClass.CREATE,
            resource_id=None,
            expected_version=None,
            container_id="999999",
        )
    )

    assert decision.allowed is False
    assert decision.reason_code == UNREADABLE


def test_a_jira_creation_is_confirmed_against_the_visible_projects() -> None:
    """Jira names its collection ``values`` and Confluence names it ``results``;
    both are read, so neither provider's envelope is assumed."""

    verifier = SourceReadPermissionVerifier(reads=StubReads(JIRA_PROJECTS))

    decision = verifier.check(
        check_for(
            SourceSystem.JIRA,
            action_class=ToolActionClass.CREATE,
            resource_id=None,
            expected_version=None,
            container_id="KAN",
        )
    )

    assert decision.allowed is True


def test_the_check_reads_the_resource_it_is_about_to_write() -> None:
    """Not a cached copy and not a rule of our own: the source is asked, by id."""

    reads = StubReads(CONFLUENCE_PAGE)

    SourceReadPermissionVerifier(reads=reads).check(check_for(SourceSystem.CONFLUENCE))

    assert len(reads.calls) == 1
    assert reads.calls[0].tool_name == "getConfluencePage"
    assert reads.calls[0].arguments["pageId"] == "98483"
    assert reads.calls[0].action_class == ToolActionClass.READ
