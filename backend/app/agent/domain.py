from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.identity import SecurityContext
from app.mcp.domain import ToolActionClass


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: tuple[dict[str, Any], ...]
    allowed_tool_names: tuple[str, ...] = ()
    max_steps: int = Field(default=8, ge=1, le=20)
    correlation_id: str


class ProposedToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    action_class: ToolActionClass
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    tool_calls: tuple[ProposedToolCall, ...] = ()
    model_name: str
    model_version: str | None = None


class LLMProvider(Protocol):
    """Provider-neutral LLM contract. The Groq SDK belongs in an adapter."""

    def generate(self, *, request: LLMRequest, context: SecurityContext) -> LLMResponse: ...
