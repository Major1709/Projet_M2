from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.core.identity import SecurityContext


class SourceSystem(StrEnum):
    JIRA = "jira"
    CONFLUENCE = "confluence"
    FIGMA = "figma"
    KNOWLEDGE = "knowledge"


class ToolActionClass(StrEnum):
    READ = "READ"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SYNC = "SYNC"
    ADMIN = "ADMIN"

    @property
    def is_external_mutation(self) -> bool:
        return self in {
            ToolActionClass.CREATE,
            ToolActionClass.UPDATE,
            ToolActionClass.DELETE,
            ToolActionClass.SYNC,
        }


class MCPToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: SourceSystem
    tool_name: str = Field(min_length=1, max_length=200)
    action_class: ToolActionClass
    arguments: dict[str, Any]
    correlation_id: str = Field(min_length=1, max_length=200)


class MCPExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    succeeded: bool
    partial: bool = False
    external_ids: tuple[str, ...] = ()
    error_code: str | None = None
    safe_message: str | None = None


class PermissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    decision_id: str
    reason_code: str | None = None


class PermissionCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    context: SecurityContext
    call: MCPToolCall


class MCPProvider(StrEnum):
    ATLASSIAN = "atlassian"
    FIGMA = "figma"


class MCPReadSourceSystem(StrEnum):
    ATLASSIAN = "atlassian"
    JIRA = "jira"
    CONFLUENCE = "confluence"
    FIGMA = "figma"


class MCPContentKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class MCPReadCommand(BaseModel):
    """A caller-selected read tool. Provider bindings are never accepted here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: MCPReadSourceSystem
    tool_name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class MCPReadBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    calls: tuple[MCPReadCommand, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_single_source_batch(self) -> "MCPReadBatch":
        if len({call.source_system for call in self.calls}) != 1:
            raise ValueError("An MCP read batch must target one source system")
        return self


class MCPReadToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: MCPReadSourceSystem
    tool_name: str = Field(min_length=1, max_length=200)
    action_class: ToolActionClass
    arguments: dict[str, JsonValue]
    correlation_id: str = Field(min_length=1, max_length=200)


class MCPReadContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: MCPContentKind
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str | None = None
    data: str | None = None
    mime_type: str | None = None

    @model_validator(mode="after")
    def validate_content_shape(self) -> "MCPReadContent":
        if self.kind == MCPContentKind.TEXT:
            if self.text is None or self.data is not None or self.mime_type is not None:
                raise ValueError("Text MCP content has an invalid shape")
        elif self.data is None or self.mime_type is None or self.text is not None:
            raise ValueError("Image MCP content has an invalid shape")
        return self


class MCPReadProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: MCPProvider
    source_system: MCPReadSourceSystem
    server_id: str
    source_origin: str
    tool_name: str
    protocol_version: str
    input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    correlation_id: str
    retrieved_at: datetime
    resource_reference: str | None = None
    source_complete: bool = False


class MCPReadResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    content: tuple[MCPReadContent, ...]
    structured_content: JsonValue | None = None
    provenance: MCPReadProvenance


class MCPReadBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    results: tuple[MCPReadResult, ...]
