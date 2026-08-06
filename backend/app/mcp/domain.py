from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(frozen=True)

    source_system: SourceSystem
    tool_name: str = Field(min_length=1, max_length=200)
    action_class: ToolActionClass
    arguments: dict[str, Any]
    correlation_id: str = Field(min_length=1, max_length=200)


class MCPExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    succeeded: bool
    partial: bool = False
    external_ids: tuple[str, ...] = ()
    error_code: str | None = None
    safe_message: str | None = None


class PermissionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    decision_id: str
    reason_code: str | None = None


class PermissionCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    context: SecurityContext
    call: MCPToolCall
