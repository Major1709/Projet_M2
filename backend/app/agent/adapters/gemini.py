"""Gemini, through its OpenAI-compatible surface, on the shared socle.

Google exposes Gemini both natively and behind a chat-completions layer. This adapter
uses the second, and that is the whole reason the switch is cheap: the native shape
speaks ``contents``/``parts``/``functionDeclarations``, which shares nothing with the
bounding, tool-call parsing and action-class handling already written and tested in
:mod:`app.agent.adapters.openai_compatible`. Going native would not have been a new
adapter, it would have been a second implementation of all of it.

The compatibility layer is not the native API, and the difference is worth naming
rather than discovering: it is the OpenAI shape Google chose to support, so a field
Groq accepts is not guaranteed here. ``reasoning_format`` is the concrete case -- it
stays with the Groq subclass, because sending it here fails the whole request instead
of being ignored.

Nothing about the credential handling changes. The endpoint is pinned and validated
at import like every other, the key is read from a file and never logged, and the
connection is nailed to an address that was approved before the key was loaded.
"""

from typing import Final

from app.agent.adapters.openai_compatible import OpenAICompatibleLLMProvider

__all__ = ["GEMINI_ENDPOINT", "MAX_COMPLETION_TOKENS", "GeminiLLMProvider"]

GEMINI_ENDPOINT: Final = "https://generativelanguage.googleapis.com/v1beta/openai"

# Deliberately conservative, and lower than Groq's. The flash-lite family's real
# output ceiling is a property of the served model, and this value has not been
# measured against it -- so it is set where it cannot cause a rejected request, well
# above the few hundred tokens a tool-calling turn actually needs. Raise it only after
# measuring, not on the strength of a documentation page.
MAX_COMPLETION_TOKENS: Final = 8_192


class GeminiLLMProvider(OpenAICompatibleLLMProvider):
    """Chat completions against a pinned Gemini endpoint. The API key never leaves here."""

    ENDPOINT = GEMINI_ENDPOINT
    PROVIDER_LABEL = "gemini"
    COMPLETION_CEILING = MAX_COMPLETION_TOKENS
    # Empty on purpose, and not an oversight: the compatibility layer refuses a
    # request carrying a field it does not know, so this adapter sends the plain
    # chat-completions shape and nothing beyond it.
