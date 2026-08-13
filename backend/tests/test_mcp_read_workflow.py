import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.audit.adapters.memory import InMemoryAuditSink
from app.audit.domain import AuditEventType
from app.core.config import Settings
from app.core.identity import SecurityContext
from app.mcp.domain import (
    MCPProvider,
    MCPReadBatch,
    MCPReadCommand,
    MCPReadToolCall,
    ToolActionClass,
)
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.errors import (
    MCPAuditUnavailable,
    MCPCallTimeout,
    MCPInputRejected,
    MCPInvalidResponse,
    MCPProtocolRejected,
    MCPProviderDisabled,
    MCPResponseTooLarge,
    MCPSchemaRejected,
    MCPToolDenied,
)
from app.mcp.ports import (
    MCPReadSession,
    RemoteContentBlock,
    RemoteToolDescription,
    RemoteToolResult,
)
from app.mcp.read_workflow import MAX_IMAGE_BYTES, MAX_TEXT_BYTES, MCPReadWorkflow
from app.mcp.registry import (
    FIGMA_FILE_KEY,
    FIGMA_NODE_ID,
    JIRA_SOURCE_ORIGIN,
    MCPBindingKind,
    MCPToolRegistry,
    ToolContract,
    schema_sha256,
)

JIRA_CLOUD_ID = UUID("11111111-1111-4111-8111-111111111111")
CONFLUENCE_CLOUD_ID = UUID("22222222-2222-4222-8222-222222222222")
CONTEXT = SecurityContext(tenant_id="tenant-a", user_id="user-a")
_MATCH_CONTRACT = object()


class SpySession:
    def __init__(
        self,
        *,
        tools: tuple[RemoteToolDescription, ...],
        result: RemoteToolResult | None = None,
        protocol_version: str = "2026-07-28",
    ) -> None:
        self._protocol_version = protocol_version
        self.tools = tools
        self.result = result or RemoteToolResult(
            content=(RemoteContentBlock(kind="text", text="safe result"),),
        )
        self.list_count = 0
        self.call_count = 0
        self.called_tool: str | None = None
        self.called_arguments: dict[str, Any] | None = None
        self.list_delay = 0.0
        self.call_delay = 0.0

    @property
    def protocol_version(self) -> str:
        return self._protocol_version

    async def list_tools(self) -> tuple[RemoteToolDescription, ...]:
        self.list_count += 1
        await asyncio.sleep(self.list_delay)
        return self.tools

    async def call_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> RemoteToolResult:
        self.call_count += 1
        await asyncio.sleep(self.call_delay)
        self.called_tool = tool_name
        self.called_arguments = arguments
        return self.result


class SpyTransport:
    def __init__(self, session: SpySession) -> None:
        self.session = session
        self.connect_count = 0
        self.providers: list[object] = []

    @asynccontextmanager
    async def connect(
        self,
        *,
        provider: object,
        context: SecurityContext,
    ) -> AsyncIterator[MCPReadSession]:
        del context
        self.connect_count += 1
        self.providers.append(provider)
        yield self.session


def enabled_settings(**changes: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "repository_backend": "postgres",
        "database_host": "postgres.test.invalid",
        "database_port": 5432,
        "database_name": "pka_test",
        "database_user": "pka_test",
        "database_password_file": Path("synthetic-test-password"),
        "mcp_reads_enabled": True,
        "mcp_atlassian_enabled": True,
        "mcp_jira_enabled": True,
        "mcp_confluence_enabled": True,
        "mcp_figma_enabled": True,
        "mcp_atlassian_jira_cloud_id": JIRA_CLOUD_ID,
        "mcp_atlassian_confluence_cloud_id": CONFLUENCE_CLOUD_ID,
    }
    values.update(changes)
    return Settings(**values)


def workflow_for(
    source_system: SourceSystem,
    tool_name: str,
    *,
    settings: Settings | None = None,
    result: RemoteToolResult | None = None,
    protocol_version: str = "2026-07-28",
    audit_sink: Any | None = None,
    approved_output_schema: dict[str, Any] | None = None,
    listed_output_schema: dict[str, Any] | None | object = _MATCH_CONTRACT,
) -> tuple[MCPReadWorkflow, SpyTransport, SpySession]:
    registry = MCPToolRegistry()
    contract = registry.get(source_system, tool_name)
    assert contract is not None
    if approved_output_schema is not None:
        contract = replace(contract, provider_output_schema=approved_output_schema)
        registry = MCPToolRegistry((contract,))
    remote_output_schema = (
        contract.provider_output_schema
        if listed_output_schema is _MATCH_CONTRACT
        else listed_output_schema
    )
    assert remote_output_schema is None or isinstance(remote_output_schema, dict)
    session = SpySession(
        tools=(
            RemoteToolDescription(
                name=tool_name,
                input_schema=contract.provider_input_schema,
                output_schema=remote_output_schema,
            ),
        ),
        result=result,
        protocol_version=protocol_version,
    )
    transport = SpyTransport(session)
    return (
        MCPReadWorkflow(
            settings=settings or enabled_settings(),
            registry=registry,
            transport=transport,
            audit_sink=audit_sink or InMemoryAuditSink(),
        ),
        transport,
        session,
    )


def run_call(
    workflow: MCPReadWorkflow,
    *,
    source_system: SourceSystem,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    action_class: ToolActionClass = ToolActionClass.READ,
):
    return asyncio.run(
        workflow.execute_call(
            call=MCPReadToolCall(
                source_system=source_system,
                tool_name=tool_name,
                action_class=action_class,
                arguments=arguments or {},
                correlation_id="corr-test-1",
            ),
            context=CONTEXT,
        )
    )


def test_provider_disabled_refuses_before_network() -> None:
    workflow, transport, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        settings=Settings(environment="test"),
    )

    with pytest.raises(MCPProviderDisabled):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert transport.connect_count == 0
    assert session.list_count == 0
    assert session.call_count == 0


@pytest.mark.parametrize(
    ("source_system", "tool_name", "action_class"),
    [
        (SourceSystem.FIGMA, "use_figma", ToolActionClass.READ),
        (SourceSystem.FIGMA, "whoami", ToolActionClass.UPDATE),
        (SourceSystem.JIRA, "createJiraIssue", ToolActionClass.CREATE),
    ],
)
def test_unknown_and_mutating_tools_never_reach_network(
    source_system: SourceSystem,
    tool_name: str,
    action_class: ToolActionClass,
) -> None:
    workflow, transport, session = workflow_for(SourceSystem.FIGMA, "whoami")

    with pytest.raises(MCPToolDenied):
        run_call(
            workflow,
            source_system=source_system,
            tool_name=tool_name,
            action_class=action_class,
        )

    assert transport.connect_count == 0
    assert session.list_count == 0
    assert session.call_count == 0


@pytest.mark.parametrize("injected_name", ["fileKey", "nodeId", "endpoint", "tenant_id"])
def test_caller_cannot_inject_figma_or_identity_bindings(injected_name: str) -> None:
    workflow, transport, session = workflow_for(SourceSystem.FIGMA, "get_metadata")

    with pytest.raises(MCPInputRejected):
        run_call(
            workflow,
            source_system=SourceSystem.FIGMA,
            tool_name="get_metadata",
            arguments={injected_name: "attacker-controlled"},
        )

    assert transport.connect_count == 0
    assert session.list_count == 0
    assert session.call_count == 0


@pytest.mark.parametrize("injected_name", ["cloudId", "endpoint", "tenant_id", "user_id"])
def test_caller_cannot_inject_atlassian_bindings(injected_name: str) -> None:
    workflow, transport, session = workflow_for(SourceSystem.JIRA, "getJiraIssue")

    with pytest.raises(MCPInputRejected):
        run_call(
            workflow,
            source_system=SourceSystem.JIRA,
            tool_name="getJiraIssue",
            arguments={"issueIdOrKey": "PKA-1", injected_name: "attacker-controlled"},
        )

    assert transport.connect_count == 0
    assert session.list_count == 0
    assert session.call_count == 0


def test_schema_drift_is_refused_after_list_and_before_call() -> None:
    workflow, transport, session = workflow_for(SourceSystem.FIGMA, "whoami")
    session.tools = (
        RemoteToolDescription(
            name="whoami",
            input_schema={
                "type": "object",
                "properties": {"derived": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
    )

    with pytest.raises(MCPSchemaRejected):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert transport.connect_count == 1
    assert session.list_count == 1
    assert session.call_count == 0


def test_unapproved_protocol_is_refused_before_tool_list() -> None:
    workflow, _, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        protocol_version="2025-06-18",
    )

    with pytest.raises(MCPProtocolRejected):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert session.list_count == 0
    assert session.call_count == 0


def test_atlassian_negotiated_protocol_is_approved() -> None:
    """2025-11-25 is the highest revision the Atlassian MCP server speaks."""
    workflow, _, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        protocol_version="2025-11-25",
    )

    result = run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert result.provenance.protocol_version == "2025-11-25"
    assert session.call_count == 1


def test_figma_target_is_injected_and_result_has_provenance() -> None:
    workflow, _, session = workflow_for(SourceSystem.FIGMA, "get_screenshot")

    result = run_call(
        workflow,
        source_system=SourceSystem.FIGMA,
        tool_name="get_screenshot",
    )

    assert session.called_arguments == {"fileKey": FIGMA_FILE_KEY, "nodeId": FIGMA_NODE_ID}
    assert result.provenance.source_system == SourceSystem.FIGMA
    assert result.provenance.tool_name == "get_screenshot"
    assert result.provenance.protocol_version == "2026-07-28"
    assert result.provenance.correlation_id == "corr-test-1"
    assert result.provenance.input_schema_sha256
    assert result.provenance.arguments_sha256
    assert result.provenance.binding_fingerprint
    assert result.provenance.output_schema_sha256 is None
    assert result.provenance.resource_reference is None
    assert result.provenance.source_complete is False
    assert result.content[0].text == "safe result"
    assert result.structured_content is None


def test_atlassian_cloud_id_is_injected_from_distinct_binding() -> None:
    workflow, _, session = workflow_for(SourceSystem.JIRA, "getJiraIssue")

    run_call(
        workflow,
        source_system=SourceSystem.JIRA,
        tool_name="getJiraIssue",
        arguments={"issueIdOrKey": "PKA-1"},
    )

    assert session.called_arguments == {
        "issueIdOrKey": "PKA-1",
        "cloudId": str(JIRA_CLOUD_ID),
    }


def test_resource_reference_is_derived_from_validated_arguments() -> None:
    workflow, _, _ = workflow_for(SourceSystem.JIRA, "getJiraIssue")

    result = run_call(
        workflow,
        source_system=SourceSystem.JIRA,
        tool_name="getJiraIssue",
        arguments={"issueIdOrKey": "PKA-1"},
    )

    assert result.provenance.resource_reference == f"{JIRA_SOURCE_ORIGIN}/browse/PKA-1"
    # No authenticated output schema attests the body is whole, so the citation
    # identifies the resource without claiming the read was exhaustive.
    assert result.provenance.source_complete is False


def test_resource_reference_cannot_escape_its_path_segment() -> None:
    """The value is ours, but percent-encoding keeps a hostile key inside its segment."""
    workflow, _, _ = workflow_for(SourceSystem.JIRA, "getJiraIssue")

    result = run_call(
        workflow,
        source_system=SourceSystem.JIRA,
        tool_name="getJiraIssue",
        arguments={"issueIdOrKey": "../../evil?x=1#y"},
    )

    reference = result.provenance.resource_reference
    assert reference == f"{JIRA_SOURCE_ORIGIN}/browse/..%2F..%2Fevil%3Fx%3D1%23y"
    assert reference is not None and reference.startswith(f"{JIRA_SOURCE_ORIGIN}/browse/")


def test_tools_without_a_citable_identifier_have_no_resource_reference() -> None:
    workflow, _, _ = workflow_for(SourceSystem.CONFLUENCE, "getConfluenceSpaces")

    result = run_call(
        workflow,
        source_system=SourceSystem.CONFLUENCE,
        tool_name="getConfluenceSpaces",
    )

    assert result.provenance.resource_reference is None


def test_citation_path_must_name_a_required_public_argument() -> None:
    """An optional argument would silently yield a null citation at runtime."""
    schema = {
        "type": "object",
        "properties": {"pageId": {"type": "string"}},
        "additionalProperties": False,
    }

    with pytest.raises(ValueError, match="not a required public argument"):
        ToolContract(
            server_id="atlassian-rovo",
            provider=MCPProvider.ATLASSIAN,
            source_system=SourceSystem.CONFLUENCE,
            source_origin="https://example.invalid",
            tool_name="probe",
            binding_kind=MCPBindingKind.CONFLUENCE,
            public_input_schema=schema,
            provider_input_schema=schema,
            resource_reference_path="/wiki/pages/{pageId}",
        )


def test_text_and_structured_size_limit_is_enforced() -> None:
    result = RemoteToolResult(
        content=(RemoteContentBlock(kind="text", text="x" * MAX_TEXT_BYTES),),
        structured_content={"extra": "x"},
    )
    output_schema = {
        "type": "object",
        "properties": {"extra": {"type": "string"}},
        "required": ["extra"],
        "additionalProperties": False,
    }
    workflow, _, _ = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        result=result,
        approved_output_schema=output_schema,
    )

    with pytest.raises(MCPResponseTooLarge):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")


def test_image_size_and_mime_are_validated() -> None:
    oversized = base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode()
    workflow, _, _ = workflow_for(
        SourceSystem.FIGMA,
        "get_screenshot",
        result=RemoteToolResult(
            content=(
                RemoteContentBlock(kind="image", data=oversized, mime_type="image/png"),
            )
        ),
    )
    with pytest.raises(MCPResponseTooLarge):
        run_call(
            workflow,
            source_system=SourceSystem.FIGMA,
            tool_name="get_screenshot",
        )

    workflow, _, _ = workflow_for(
        SourceSystem.FIGMA,
        "get_screenshot",
        result=RemoteToolResult(
            content=(
                RemoteContentBlock(
                    kind="image",
                    data=base64.b64encode(b"safe").decode(),
                    mime_type="image/svg+xml",
                ),
            )
        ),
    )
    with pytest.raises(MCPInvalidResponse):
        run_call(
            workflow,
            source_system=SourceSystem.FIGMA,
            tool_name="get_screenshot",
        )


def test_resource_link_response_is_never_followed_or_returned() -> None:
    workflow, _, _ = workflow_for(
        SourceSystem.FIGMA,
        "get_design_context",
        result=RemoteToolResult(
            content=(RemoteContentBlock(kind="unsupported"),),
        ),
    )

    with pytest.raises(MCPInvalidResponse):
        run_call(
            workflow,
            source_system=SourceSystem.FIGMA,
            tool_name="get_design_context",
        )


def test_non_json_structured_response_is_rejected() -> None:
    output_schema = {"type": "object"}
    workflow, _, _ = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        result=RemoteToolResult(
            content=(),
            structured_content={"invalid": float("nan")},
        ),
        approved_output_schema=output_schema,
    )

    with pytest.raises(MCPInvalidResponse):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")


def test_batch_is_limited_to_three_calls_before_execution() -> None:
    command = MCPReadCommand(source_system=SourceSystem.FIGMA, tool_name="whoami")
    with pytest.raises(ValidationError):
        MCPReadBatch(calls=(command, command, command, command))


def test_batch_cannot_mix_source_systems_before_execution() -> None:
    with pytest.raises(ValidationError, match="one source system"):
        MCPReadBatch(
            calls=(
                MCPReadCommand(source_system=SourceSystem.FIGMA, tool_name="whoami"),
                MCPReadCommand(
                    source_system=SourceSystem.JIRA,
                    tool_name="getJiraIssue",
                    arguments={"issueIdOrKey": "PKA-1"},
                ),
            )
        )


def test_remote_output_schema_is_refused_when_contract_has_none() -> None:
    workflow, transport, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        listed_output_schema={"type": "object"},
    )

    with pytest.raises(MCPSchemaRejected):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert transport.connect_count == 1
    assert session.list_count == 1
    assert session.call_count == 0


def test_structured_content_is_refused_when_contract_has_no_output_schema() -> None:
    workflow, _, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        result=RemoteToolResult(content=(), structured_content={"count": 1}),
    )

    with pytest.raises(MCPSchemaRejected):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert session.call_count == 1


def test_pinned_output_schema_drift_is_refused_before_call() -> None:
    approved = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    }
    workflow, _, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        approved_output_schema=approved,
        listed_output_schema={"type": "object", "additionalProperties": True},
    )

    with pytest.raises(MCPSchemaRejected):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert session.call_count == 0


def test_pinned_output_schema_validates_structured_content_and_provenance() -> None:
    approved = {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    }
    invalid_workflow, _, invalid_session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        approved_output_schema=approved,
        result=RemoteToolResult(content=(), structured_content={"count": "one"}),
    )
    with pytest.raises(MCPSchemaRejected):
        run_call(
            invalid_workflow,
            source_system=SourceSystem.FIGMA,
            tool_name="whoami",
        )
    assert invalid_session.call_count == 1

    valid_workflow, _, _ = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        approved_output_schema=approved,
        result=RemoteToolResult(content=(), structured_content={"count": 1}),
    )
    result = run_call(
        valid_workflow,
        source_system=SourceSystem.FIGMA,
        tool_name="whoami",
    )
    assert result.structured_content == {"count": 1}
    assert result.provenance.output_schema_sha256 == schema_sha256(approved)


def test_audit_authorization_failure_prevents_all_network() -> None:
    class FailingAuditSink:
        def append(self, event: object) -> None:
            del event
            raise RuntimeError("synthetic audit outage")

    workflow, transport, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        audit_sink=FailingAuditSink(),
    )

    with pytest.raises(MCPAuditUnavailable, match="audit trail"):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert transport.connect_count == 0
    assert session.list_count == 0
    assert session.call_count == 0


def test_final_audit_failure_withholds_successful_result() -> None:
    class FailOnSecondAuditSink:
        def __init__(self) -> None:
            self.calls = 0

        def append(self, event: object) -> None:
            del event
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic final audit outage")

    audit = FailOnSecondAuditSink()
    workflow, transport, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        audit_sink=audit,
    )

    with pytest.raises(MCPAuditUnavailable, match="audit trail"):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert audit.calls == 2
    assert transport.connect_count == 1
    assert session.call_count == 1


def test_audit_events_are_metadata_only_and_ordered() -> None:
    audit = InMemoryAuditSink()
    sensitive_argument = "PKA-SENSITIVE-ISSUE-1"
    workflow, _, _ = workflow_for(
        SourceSystem.JIRA,
        "getJiraIssue",
        audit_sink=audit,
    )

    run_call(
        workflow,
        source_system=SourceSystem.JIRA,
        tool_name="getJiraIssue",
        arguments={"issueIdOrKey": sensitive_argument},
    )

    events = audit.snapshot()
    assert [event.event_type for event in events] == [
        AuditEventType.MCP_READ_AUTHORIZED,
        AuditEventType.MCP_READ_COMPLETED,
    ]
    authorized = events[0].details
    assert authorized["arguments_sha256"]
    assert authorized["binding_fingerprint"]
    serialized = json.dumps([event.model_dump(mode="json") for event in events])
    assert sensitive_argument not in serialized
    assert "safe result" not in serialized


def test_local_denial_is_audited_without_network() -> None:
    audit = InMemoryAuditSink()
    workflow, transport, session = workflow_for(
        SourceSystem.FIGMA,
        "whoami",
        audit_sink=audit,
    )

    with pytest.raises(MCPToolDenied):
        run_call(
            workflow,
            source_system=SourceSystem.FIGMA,
            tool_name="use_figma",
        )

    events = audit.snapshot()
    assert len(events) == 1
    assert events[0].event_type == AuditEventType.MCP_READ_FAILED
    assert events[0].details["error_code"] == "MCP_TOOL_DENIED"
    assert transport.connect_count == 0
    assert session.call_count == 0


def test_global_read_budget_covers_list_and_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.mcp.read_workflow as read_workflow

    monkeypatch.setattr(read_workflow, "MCP_READ_BUDGET_SECONDS", 0.02)
    workflow, _, session = workflow_for(SourceSystem.FIGMA, "whoami")
    session.list_delay = 0.015
    session.call_delay = 0.015

    with pytest.raises(MCPCallTimeout):
        run_call(workflow, source_system=SourceSystem.FIGMA, tool_name="whoami")

    assert session.list_count == 1
    assert session.call_count == 1
