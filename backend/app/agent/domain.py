from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.identity import SecurityContext
from app.mcp.domain import ToolActionClass


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: tuple[dict[str, Any], ...]
    # What the model is shown. JSON-Schema tool descriptions, already public: the
    # server-side bindings are injected after the model has chosen, so nothing here
    # reveals a site, a file key, or a credential.
    tools: tuple[dict[str, Any], ...] = ()
    # What the model is allowed to have chosen. Kept separate from ``tools`` on
    # purpose: a provider can return a name that was never offered, and the adapter
    # refuses it when this tuple is non-empty. It is a boundary check, not the
    # authority -- the registry allowlist in the read workflow remains that.
    allowed_tool_names: tuple[str, ...] = ()
    max_steps: int = Field(default=8, ge=1, le=20)
    # Asked for per request, not fixed by the adapter. A provider counts the whole
    # budget -- prompt plus the completion ceiling -- against the credential's
    # allowance, so always demanding the model's maximum makes every call as
    # expensive as the largest one it could ever need.
    max_completion_tokens: int = Field(default=2_048, ge=64, le=16_384)
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
    """Provider-neutral LLM contract. The Groq client belongs in an adapter.

    Asynchronous because the whole read path is: a blocking model call inside the
    orchestration loop would hold the event loop for the length of an inference,
    starving every other request in the process.
    """

    @property
    def model_name(self) -> str: ...

    async def generate(self, *, request: LLMRequest, context: SecurityContext) -> LLMResponse: ...
