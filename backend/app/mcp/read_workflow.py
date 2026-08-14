import base64
import binascii
import hashlib
import json
import logging
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

import anyio
from jsonschema import Draft202012Validator

from app.audit.domain import AuditEvent, AuditEventType
from app.audit.ports import AuditSink
from app.core.config import Settings
from app.core.identity import SecurityContext
from app.mcp.domain import (
    MCPBindingKind,
    MCPContentKind,
    MCPProvider,
    MCPReadBatch,
    MCPReadBatchResult,
    MCPReadContent,
    MCPReadProvenance,
    MCPReadResult,
    MCPReadToolCall,
    ToolActionClass,
)
from app.mcp.errors import (
    MCPAuditUnavailable,
    MCPBindingUnavailable,
    MCPCallTimeout,
    MCPInputRejected,
    MCPInvalidResponse,
    MCPProtocolRejected,
    MCPProviderDisabled,
    MCPReadError,
    MCPResponseTooLarge,
    MCPSchemaRejected,
    MCPToolDenied,
    MCPTransportFailure,
)
from app.mcp.ports import MCPReadTransport, RemoteContentBlock, RemoteToolResult
from app.mcp.registry import (
    APPROVED_PROTOCOL_VERSIONS,
    FIGMA_FILE_KEY,
    FIGMA_NODE_ID,
    MCPToolRegistry,
    ToolContract,
    canonical_json_sha256,
    schema_sha256,
)

MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_CONTENT_BLOCKS = 64
MCP_READ_BUDGET_SECONDS = 30.0
APPROVED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

logger = logging.getLogger(__name__)


class MCPReadWorkflow:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: MCPToolRegistry,
        transport: MCPReadTransport,
        audit_sink: AuditSink,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._transport = transport
        self._audit_sink = audit_sink

    async def execute_batch(
        self,
        batch: MCPReadBatch,
        context: SecurityContext,
    ) -> MCPReadBatchResult:
        # Pydantic enforces the per-turn budget before any transport is opened.
        results = []
        turn_id = uuid4().hex
        for index, command in enumerate(batch.calls, start=1):
            call = MCPReadToolCall(
                source_system=command.source_system,
                tool_name=command.tool_name,
                action_class=ToolActionClass.READ,
                arguments=command.arguments,
                correlation_id=f"{turn_id}:{index}",
            )
            results.append(await self.execute_call(call=call, context=context))
        return MCPReadBatchResult(results=tuple(results))

    async def execute_call(
        self,
        *,
        call: MCPReadToolCall,
        context: SecurityContext,
    ) -> MCPReadResult:
        started_at = monotonic()
        try:
            contract = self._authorize_locally(call)
            bound_arguments = self._bind_and_validate_arguments(contract, call.arguments)
        except MCPReadError as error:
            await self._append_local_refusal_audit(call, context, error)
            logger.warning(
                "MCP read refused before transport",
                extra={
                    "mcp_error_code": error.code,
                    "mcp_source": call.source_system,
                    "correlation_id": call.correlation_id,
                },
            )
            raise

        await self._append_audit(
            event_type=AuditEventType.MCP_READ_AUTHORIZED,
            contract=contract,
            context=context,
            correlation_id=call.correlation_id,
            details={
                "arguments_sha256": canonical_json_sha256(bound_arguments),
                "binding_fingerprint": self._binding_fingerprint(
                    contract,
                    context,
                    bound_arguments,
                ),
                "input_schema_sha256": contract.provider_input_schema_sha256,
                "output_schema_sha256": contract.provider_output_schema_sha256,
                "policy_version": contract.policy_version,
            },
        )
        try:
            with anyio.fail_after(MCP_READ_BUDGET_SECONDS):
                async with self._transport.connect(
                    provider=contract.provider,
                    binding=contract.binding_kind,
                    context=context,
                ) as session:
                    if session.protocol_version not in APPROVED_PROTOCOL_VERSIONS:
                        raise MCPProtocolRejected()
                    listed_tools = await session.list_tools()
                    matching = [tool for tool in listed_tools if tool.name == contract.tool_name]
                    if len(matching) != 1:
                        raise MCPSchemaRejected()
                    listed_tool = matching[0]
                    if (
                        schema_sha256(listed_tool.input_schema)
                        != contract.provider_input_schema_sha256
                    ):
                        raise MCPSchemaRejected()
                    self._validate_listed_output_schema(contract, listed_tool.output_schema)
                    remote_result = await session.call_tool(
                        tool_name=contract.tool_name,
                        arguments=bound_arguments,
                    )
                    result = self._normalize_result(
                        remote_result=remote_result,
                        contract=contract,
                        context=context,
                        protocol_version=session.protocol_version,
                        bound_arguments=bound_arguments,
                        correlation_id=call.correlation_id,
                    )
        except TimeoutError as error:
            timeout = MCPCallTimeout()
            await self._append_failed_audit(timeout, contract, context, call.correlation_id)
            raise timeout from error
        except MCPReadError as error:
            await self._append_failed_audit(error, contract, context, call.correlation_id)
            logger.warning(
                "MCP read refused",
                extra={
                    "mcp_error_code": error.code,
                    "mcp_provider": contract.provider,
                    "mcp_tool": contract.tool_name,
                    "correlation_id": call.correlation_id,
                },
            )
            raise
        except Exception as error:
            failure = MCPTransportFailure()
            await self._append_failed_audit(failure, contract, context, call.correlation_id)
            logger.exception(
                "MCP read failed unexpectedly",
                extra={
                    "mcp_error_code": failure.code,
                    "mcp_provider": contract.provider,
                    "mcp_tool": contract.tool_name,
                    "correlation_id": call.correlation_id,
                },
            )
            raise failure from error

        await self._append_audit(
            event_type=AuditEventType.MCP_READ_COMPLETED,
            contract=contract,
            context=context,
            correlation_id=call.correlation_id,
            details={
                "content_blocks": len(result.content),
                "duration_ms": round((monotonic() - started_at) * 1_000),
                "input_schema_sha256": contract.provider_input_schema_sha256,
                "output_schema_sha256": contract.provider_output_schema_sha256,
                "policy_version": contract.policy_version,
                "protocol_version": result.provenance.protocol_version,
            },
        )

        logger.info(
            "MCP read completed",
            extra={
                "mcp_provider": contract.provider,
                "mcp_tool": contract.tool_name,
                "correlation_id": call.correlation_id,
                "duration_ms": round((monotonic() - started_at) * 1_000),
                "content_blocks": len(result.content),
            },
        )
        return result

    async def _append_local_refusal_audit(
        self,
        call: MCPReadToolCall,
        context: SecurityContext,
        error: MCPReadError,
    ) -> None:
        provider = (
            MCPProvider.FIGMA
            if call.source_system.value == MCPProvider.FIGMA.value
            else MCPProvider.ATLASSIAN
        )
        event = AuditEvent(
            event_type=AuditEventType.MCP_READ_FAILED,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            correlation_id=call.correlation_id,
            details={
                "error_code": error.code,
                "provider": provider.value,
                "source_system": call.source_system.value,
                "tool_name": call.tool_name,
            },
        )
        try:
            await anyio.to_thread.run_sync(self._audit_sink.append, event)
        except Exception:
            raise MCPAuditUnavailable() from None

    async def _append_failed_audit(
        self,
        error: MCPReadError,
        contract: ToolContract,
        context: SecurityContext,
        correlation_id: str,
    ) -> None:
        await self._append_audit(
            event_type=AuditEventType.MCP_READ_FAILED,
            contract=contract,
            context=context,
            correlation_id=correlation_id,
            details={
                "error_code": error.code,
                "policy_version": contract.policy_version,
            },
        )

    async def _append_audit(
        self,
        *,
        event_type: AuditEventType,
        contract: ToolContract,
        context: SecurityContext,
        correlation_id: str,
        details: dict[str, Any],
    ) -> None:
        event = AuditEvent(
            event_type=event_type,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            correlation_id=correlation_id,
            details={
                "provider": contract.provider.value,
                "server_id": contract.server_id,
                "source_system": contract.source_system.value,
                "tool_name": contract.tool_name,
                **details,
            },
        )
        try:
            await anyio.to_thread.run_sync(self._audit_sink.append, event)
        except Exception:
            raise MCPAuditUnavailable() from None

    @staticmethod
    def _validate_listed_output_schema(
        contract: ToolContract,
        remote_output_schema: dict[str, Any] | None,
    ) -> None:
        if contract.provider_output_schema is None:
            if remote_output_schema is not None:
                raise MCPSchemaRejected()
            return
        if (
            remote_output_schema is None
            or schema_sha256(remote_output_schema)
            != contract.provider_output_schema_sha256
        ):
            raise MCPSchemaRejected()

    def _authorize_locally(self, call: MCPReadToolCall) -> ToolContract:
        if call.action_class != ToolActionClass.READ:
            raise MCPToolDenied()
        contract = self._registry.get(call.source_system, call.tool_name)
        if contract is None or contract.action_class != ToolActionClass.READ:
            raise MCPToolDenied()
        if not self._settings.mcp_reads_enabled:
            raise MCPProviderDisabled()
        if contract.provider == MCPProvider.ATLASSIAN:
            if not self._settings.mcp_atlassian_enabled:
                raise MCPProviderDisabled()
            if (
                contract.binding_kind == MCPBindingKind.JIRA
                and not self._settings.mcp_jira_enabled
            ):
                raise MCPProviderDisabled()
            if (
                contract.binding_kind == MCPBindingKind.CONFLUENCE
                and not self._settings.mcp_confluence_enabled
            ):
                raise MCPProviderDisabled()
        elif not self._settings.mcp_figma_enabled:
            raise MCPProviderDisabled()
        return contract

    def _bind_and_validate_arguments(
        self,
        contract: ToolContract,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if not Draft202012Validator(contract.public_input_schema).is_valid(arguments):
            raise MCPInputRejected()

        bound = dict(arguments)
        if contract.binding_kind == MCPBindingKind.JIRA:
            cloud_id = self._settings.mcp_atlassian_jira_cloud_id
            if cloud_id is None:
                raise MCPBindingUnavailable()
            bound["cloudId"] = str(cloud_id)
        elif contract.binding_kind == MCPBindingKind.CONFLUENCE:
            cloud_id = self._settings.mcp_atlassian_confluence_cloud_id
            if cloud_id is None:
                raise MCPBindingUnavailable()
            bound["cloudId"] = str(cloud_id)
        elif contract.binding_kind == MCPBindingKind.FIGMA:
            bound["fileKey"] = FIGMA_FILE_KEY
            bound["nodeId"] = FIGMA_NODE_ID

        if not Draft202012Validator(contract.provider_input_schema).is_valid(bound):
            raise MCPInputRejected()
        return bound

    def _normalize_result(
        self,
        *,
        remote_result: RemoteToolResult,
        contract: ToolContract,
        context: SecurityContext,
        protocol_version: str,
        bound_arguments: dict[str, Any],
        correlation_id: str,
    ) -> MCPReadResult:
        if len(remote_result.content) > MAX_CONTENT_BLOCKS:
            raise MCPInvalidResponse()

        content: list[MCPReadContent] = []
        text_bytes = 0
        image_bytes = 0
        for block in remote_result.content:
            normalized, block_size = self._normalize_block(block, contract.provider)
            if normalized.kind == MCPContentKind.TEXT:
                text_bytes += block_size
                if text_bytes > MAX_TEXT_BYTES:
                    raise MCPResponseTooLarge()
            else:
                image_bytes += block_size
                if image_bytes > MAX_IMAGE_BYTES:
                    raise MCPResponseTooLarge()
            content.append(normalized)

        structured = self._normalize_structured_content(remote_result.structured_content)
        if contract.provider_output_schema is None:
            if structured is not None:
                raise MCPSchemaRejected()
        elif not Draft202012Validator(contract.provider_output_schema).is_valid(structured):
            raise MCPSchemaRejected()
        if structured is not None:
            structured_size = len(
                json.dumps(
                    structured,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if text_bytes + structured_size > MAX_TEXT_BYTES:
                raise MCPResponseTooLarge()

        binding_fingerprint = self._binding_fingerprint(
            contract,
            context,
            bound_arguments,
        )
        provenance = MCPReadProvenance(
            provider=contract.provider,
            source_system=contract.source_system,
            server_id=contract.server_id,
            source_origin=contract.source_origin,
            tool_name=contract.tool_name,
            protocol_version=protocol_version,
            input_schema_sha256=contract.provider_input_schema_sha256,
            output_schema_sha256=contract.provider_output_schema_sha256,
            arguments_sha256=canonical_json_sha256(bound_arguments),
            binding_fingerprint=binding_fingerprint,
            policy_version=contract.policy_version,
            correlation_id=correlation_id,
            retrieved_at=datetime.now(UTC),
            # Derived from our own validated arguments, so it identifies the resource
            # asked for, not one the provider claims to have returned. source_complete
            # stays false: no authenticated output schema attests the body is whole.
            resource_reference=contract.resource_reference(bound_arguments),
        )
        return MCPReadResult(
            content=tuple(content),
            structured_content=structured,
            provenance=provenance,
        )

    @staticmethod
    def _binding_fingerprint(
        contract: ToolContract,
        context: SecurityContext,
        bound_arguments: dict[str, Any],
    ) -> str:
        binding_value = {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "provider": contract.provider,
            "source_system": contract.source_system,
            "source_origin": contract.source_origin,
            "binding_kind": contract.binding_kind,
            "cloud_id": bound_arguments.get("cloudId"),
            "file_key": bound_arguments.get("fileKey"),
            "node_id": bound_arguments.get("nodeId"),
        }
        return canonical_json_sha256(binding_value)

    @staticmethod
    def _normalize_block(
        block: RemoteContentBlock,
        provider: MCPProvider,
    ) -> tuple[MCPReadContent, int]:
        if block.kind == "text" and block.text is not None:
            encoded = block.text.encode("utf-8")
            return (
                MCPReadContent(
                    kind=MCPContentKind.TEXT,
                    text=block.text,
                    size_bytes=len(encoded),
                    sha256=hashlib.sha256(encoded).hexdigest(),
                ),
                len(encoded),
            )
        if (
            block.kind == "image"
            and provider == MCPProvider.FIGMA
            and block.data is not None
            and block.mime_type in APPROVED_IMAGE_MIME_TYPES
        ):
            try:
                decoded = base64.b64decode(block.data, validate=True)
            except (binascii.Error, ValueError) as error:
                raise MCPInvalidResponse() from error
            return (
                MCPReadContent(
                    kind=MCPContentKind.IMAGE,
                    data=block.data,
                    mime_type=block.mime_type,
                    size_bytes=len(decoded),
                    sha256=hashlib.sha256(decoded).hexdigest(),
                ),
                len(decoded),
            )
        raise MCPInvalidResponse()

    @staticmethod
    def _normalize_structured_content(value: Any) -> Any:
        if value is None:
            return None
        try:
            serialized = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            return json.loads(serialized)
        except (TypeError, ValueError, RecursionError) as error:
            raise MCPInvalidResponse() from error
