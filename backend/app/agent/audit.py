"""Fail-closed audit around any language model provider.

Written as a decorator rather than as code inside the Groq adapter, because an
audit that each new provider has to remember to write is an audit that a new
provider will eventually omit. Wrapping the port means the trail exists for every
implementation of it, including ones that do not exist yet.

Nothing here records prompt or completion text. The messages carry whatever was
read from Jira, Confluence or Figma, and copying that into the audit trail would
duplicate the corpus into a table with a different retention and a different
audience. Counts, ceilings and a fingerprint are enough to reconstruct what
happened and to recognise two identical prompts, without restating their content.
"""

import hashlib
import json
import logging
from time import monotonic
from typing import Any

import anyio.to_thread

from app.agent.domain import LLMProvider, LLMRequest, LLMResponse
from app.agent.errors import (
    LLMAuditUnavailable,
    LLMError,
    LLMRequestTooLarge,
    LLMResponseTooLarge,
)
from app.audit.domain import AuditEvent, AuditEventType
from app.audit.ports import AuditSink
from app.core.identity import SecurityContext

logger = logging.getLogger(__name__)

# Errors that mean one of our own ceilings stopped the call rather than the
# provider turning it away. Kept as an explicit set: deriving the verdict from a
# code prefix would silently reclassify every future error whose name happens to
# read like a bound.
_BOUNDED_ERRORS: tuple[type[LLMError], ...] = (LLMRequestTooLarge, LLMResponseTooLarge)


def _prompt_fingerprint(request: LLMRequest) -> str:
    """Identify a prompt without storing it.

    Sorted keys so that two structurally identical prompts fingerprint alike, and
    ``default=str`` so an unserialisable value degrades into a stable string
    instead of raising inside the audit path -- failing to fingerprint must never
    be the reason a call is refused.
    """

    payload = json.dumps(
        {"messages": request.messages, "tools": request.tools},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditedLLMProvider:
    """An ``LLMProvider`` that cannot be called without leaving a trace."""

    def __init__(self, *, provider: LLMProvider, audit_sink: AuditSink) -> None:
        self._provider = provider
        self._audit_sink = audit_sink

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    async def generate(self, *, request: LLMRequest, context: SecurityContext) -> LLMResponse:
        # Written before the call, not after. An authorization recorded first means
        # a crash, a timeout or a killed process leaves an invocation that is
        # visibly unterminated, rather than no invocation at all.
        await self._append(
            event_type=AuditEventType.LLM_INVOCATION_AUTHORIZED,
            request=request,
            context=context,
            details={},
        )

        started_at = monotonic()
        try:
            response = await self._provider.generate(request=request, context=context)
        except LLMError as error:
            bounded = isinstance(error, _BOUNDED_ERRORS)
            await self._append(
                event_type=(
                    AuditEventType.LLM_INVOCATION_BOUNDED
                    if bounded
                    else AuditEventType.LLM_INVOCATION_REFUSED
                ),
                request=request,
                context=context,
                details={
                    "error_code": error.code,
                    "duration_ms": self._elapsed_ms(started_at),
                },
            )
            raise
        except Exception as error:
            # An unexpected exception escaping an adapter is a defect, and the one
            # case where the trail matters most. Recorded under its type name only:
            # the message may carry provider text we have not bounded.
            await self._append(
                event_type=AuditEventType.LLM_INVOCATION_REFUSED,
                request=request,
                context=context,
                details={
                    "error_code": "LLM_UNEXPECTED_FAILURE",
                    "error_type": type(error).__name__,
                    "duration_ms": self._elapsed_ms(started_at),
                },
            )
            raise

        await self._append(
            event_type=AuditEventType.LLM_INVOCATION_COMPLETED,
            request=request,
            context=context,
            details={
                # Reported apart from the requested model: a provider is free to
                # serve a different build than the alias asked for, and a trail
                # that records only what we asked for cannot show that it did.
                "model_version": response.model_version,
                "text_characters": len(response.text),
                "tool_calls": [
                    {"tool_name": call.tool_name, "action_class": call.action_class.value}
                    for call in response.tool_calls
                ],
                "duration_ms": self._elapsed_ms(started_at),
            },
        )
        return response

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return int((monotonic() - started_at) * 1000)

    async def _append(
        self,
        *,
        event_type: AuditEventType,
        request: LLMRequest,
        context: SecurityContext,
        details: dict[str, Any],
    ) -> None:
        event = AuditEvent(
            event_type=event_type,
            tenant_id=context.tenant_id,
            actor_user_id=context.user_id,
            # The same identifier the MCP reads carry, so one question and the reads
            # it caused are a single trail rather than two unrelated ones.
            correlation_id=request.correlation_id,
            details={
                "model_name": self._provider.model_name,
                "max_completion_tokens": request.max_completion_tokens,
                "max_steps": request.max_steps,
                "message_count": len(request.messages),
                "tool_count": len(request.tools),
                "allowed_tool_names": list(request.allowed_tool_names),
                "prompt_sha256": _prompt_fingerprint(request),
                **details,
            },
        )
        try:
            await anyio.to_thread.run_sync(self._audit_sink.append, event)
        except Exception:
            logger.error(
                "The LLM audit trail is unavailable; the invocation is refused",
                extra={
                    "audit_event_type": event_type.value,
                    "correlation_id": request.correlation_id,
                },
            )
            raise LLMAuditUnavailable() from None
