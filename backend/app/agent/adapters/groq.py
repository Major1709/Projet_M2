"""Groq, on the shared chat-completions socle.

Everything about the wire -- bounding the response, parsing tool calls, imposing the
action class -- lives in :mod:`app.agent.adapters.openai_compatible`. What is left
here is what is true of Groq and of no one else: where it answers, what it calls
itself in a log, how much it will write, and the one request field it understands
that the others do not.

The constants are re-exported rather than moved out of sight. They are part of this
module's surface -- the suite that proves the bounds holds them by name from here --
and an extraction that quietly renamed them would have made the refactor look larger
than it is.
"""

from types import MappingProxyType
from typing import Final

from app.agent.adapters.openai_compatible import (
    CALL_TIMEOUT_SECONDS,
    MAX_API_KEY_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_TEXT_CHARACTERS,
    MAX_TOOL_ARGUMENTS_CHARACTERS,
    MAX_TOOL_CALL_ID_CHARACTERS,
    MAX_TOOL_CALLS,
    MAX_TOOL_NAME_CHARACTERS,
    MIN_API_KEY_BYTES,
    OpenAICompatibleLLMProvider,
)

__all__ = [
    "CALL_TIMEOUT_SECONDS",
    "GROQ_ENDPOINT",
    "MAX_API_KEY_BYTES",
    "MAX_COMPLETION_TOKENS",
    "MAX_RESPONSE_BYTES",
    "MAX_TEXT_CHARACTERS",
    "MAX_TOOL_ARGUMENTS_CHARACTERS",
    "MAX_TOOL_CALLS",
    "MAX_TOOL_CALL_ID_CHARACTERS",
    "MAX_TOOL_NAME_CHARACTERS",
    "MIN_API_KEY_BYTES",
    "GroqLLMProvider",
]

GROQ_ENDPOINT: Final = "https://api.groq.com/openai/v1"

# qwen3.6-27b caps completions at 16 384 tokens. This is a ceiling the adapter
# applies to whatever the caller asks for -- the ask is lowered to fit, not refused.
# Getting a shorter completion is better than a request the provider rejects
# outright, and the truncation that would follow is caught by ``finish_reason``.
MAX_COMPLETION_TOKENS: Final = 16_384


class GroqLLMProvider(OpenAICompatibleLLMProvider):
    """Chat completions against a pinned Groq endpoint. The API key never leaves here."""

    ENDPOINT = GROQ_ENDPOINT
    PROVIDER_LABEL = "groq"
    COMPLETION_CEILING = MAX_COMPLETION_TOKENS
    # qwen3.6-27b reasons before answering, and by default writes that reasoning into
    # the answer inside <think> tags. Asking for it parsed puts it in its own field,
    # so the user-facing text stays the answer.
    #
    # This holds for models that honour the parameter, which is a property of the
    # configured model rather than of this adapter. A model that ignored it would put
    # its reasoning back into ``content`` -- and from there into a rendered answer --
    # which is why ``_text_of`` strips the tags defensively rather than trusting the
    # request to have been respected.
    #
    # Groq-only, and that is the reason it sits here: Gemini rejects the whole request
    # when it receives a field it does not know.
    EXTRA_PAYLOAD = MappingProxyType({"reasoning_format": "parsed"})
