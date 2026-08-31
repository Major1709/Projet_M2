"""Reauthorise a write by reading its target, immediately before writing it.

The permission is not recomputed here, and that is the design. The delegated
credential is the authority on what its holder may see, so the check is a read of
the very resource about to be written, performed through the same hardened
pipeline as any other read -- same allowlist, same schema validation, same
server-injected binding, same audit trail. A resource the credential cannot read
is one the write must not touch, and we learn that by asking the source rather
than by keeping a copy of its rules that would drift the day someone changes a
space permission.

The same read answers the second question for free: the source states its own
version, so a target edited between the approval and the execution is caught by
comparing what the human was shown against what is there now. One round trip,
two guarantees.

Response shapes are taken from live reads against the deployment on 2026-08-31,
not from documentation:

    Confluence getConfluencePage -> version.number == 1 (integer), body a STRING
    Jira       getJiraIssue      -> fields.updated == "2026-08-19T20:24:41.681+0300"

Both are compared as opaque strings. Only the source can say what its own version
means -- an integer for one product, a timestamp with an offset for the other --
and parsing either would be inventing a semantics the provider never promised.

Honest limit: in ``development_files`` grant mode the pipeline presents a fixed
grant rather than the calling user's own delegated token, so "can the user still
see it" is really "can the grant still see it". The check becomes per-user the day
grants are per-user; nothing here changes when they are.
"""

import json
from typing import Any

import anyio
import anyio.from_thread

from app.core.identity import SecurityContext
from app.mcp.domain import (
    MCPReadSourceSystem,
    MCPReadToolCall,
    PermissionCheck,
    PermissionDecision,
    SourceSystem,
    ToolActionClass,
)
from app.mcp.errors import MCPReadError
from app.mcp.read_workflow import MCPReadWorkflow

# Returned when the source will not hand back the target at all. Deliberately the
# same answer whether the resource is gone or merely invisible: distinguishing them
# would confirm the existence of a resource to someone who cannot see it.
UNREADABLE = "SOURCE_PERMISSION_DENIED"
# The target moved after the human decided. Distinct from a denial because the
# remedy is different -- re-read and propose again, rather than obtain access.
CHANGED = "RESOURCE_CHANGED"
# The proposal names a source or a shape this verifier has no read for. Fails
# closed: an action nobody can revalidate is an action nobody may perform.
UNSUPPORTED = "SOURCE_REVALIDATION_UNAVAILABLE"


def _read_for_resource(
    source_system: SourceSystem, resource_id: str
) -> MCPReadToolCall | None:
    if source_system == SourceSystem.CONFLUENCE:
        return MCPReadToolCall(
            source_system=MCPReadSourceSystem.CONFLUENCE,
            tool_name="getConfluencePage",
            action_class=ToolActionClass.READ,
            arguments={"pageId": resource_id, "contentFormat": "markdown"},
            correlation_id="permission-check",
        )
    if source_system == SourceSystem.JIRA:
        return MCPReadToolCall(
            source_system=MCPReadSourceSystem.JIRA,
            tool_name="getJiraIssue",
            action_class=ToolActionClass.READ,
            arguments={"issueIdOrKey": resource_id},
            correlation_id="permission-check",
        )
    return None


def _read_for_container(source_system: SourceSystem) -> MCPReadToolCall | None:
    """A creation has no target, so what gets confirmed is the container.

    Enumerating rather than fetching, on purpose: both products answer "what can
    this credential see" with a list, and membership of that list is exactly the
    question. Fetching a container by id would answer a different one -- whether it
    exists -- which is not what a write needs to know.
    """

    if source_system == SourceSystem.CONFLUENCE:
        return MCPReadToolCall(
            source_system=MCPReadSourceSystem.CONFLUENCE,
            tool_name="getConfluenceSpaces",
            action_class=ToolActionClass.READ,
            arguments={},
            correlation_id="permission-check",
        )
    if source_system == SourceSystem.JIRA:
        return MCPReadToolCall(
            source_system=MCPReadSourceSystem.JIRA,
            tool_name="getVisibleJiraProjects",
            action_class=ToolActionClass.READ,
            arguments={},
            correlation_id="permission-check",
        )
    return None


def _payload_of(result: Any) -> Any:
    """The provider's own JSON, out of the normalised content blocks."""

    for block in result.content:
        if block.text is None:
            continue
        try:
            return json.loads(block.text)
        except ValueError:
            continue
    return None


def source_version_of(source_system: SourceSystem, payload: Any) -> str | None:
    """The version string the source states for a resource it just returned.

    Kept module-level and named so a test can pin it against a captured provider
    response: a path that silently stops matching would make every check pass on
    ``None == None``, which is the quiet way this control dies.
    """

    if not isinstance(payload, dict):
        return None
    if source_system == SourceSystem.CONFLUENCE:
        version = payload.get("version")
        number = version.get("number") if isinstance(version, dict) else None
        return None if number is None else str(number)
    if source_system == SourceSystem.JIRA:
        fields = payload.get("fields")
        updated = fields.get("updated") if isinstance(fields, dict) else None
        return None if updated is None else str(updated)
    return None


def _identifiers_in(payload: Any) -> set[str]:
    """Every id and key in a listing, flattened, as strings.

    The two products disagree on where a collection lives -- ``results`` for
    Confluence spaces, ``values`` for Jira projects -- and on whether a container is
    named by id or by key. Collecting all of them and asking for membership is
    exact enough for the question and survives either provider renaming its
    envelope.
    """

    found: set[str] = set()
    if not isinstance(payload, dict):
        return found
    for key in ("results", "values"):
        for entry in payload.get(key) or []:
            if not isinstance(entry, dict):
                continue
            for name in ("id", "key"):
                value = entry.get(name)
                if value is not None:
                    found.add(str(value))
    return found


class SourceReadPermissionVerifier:
    """Confirms a write's target by reading it through the ordinary read pipeline."""

    def __init__(self, *, reads: MCPReadWorkflow) -> None:
        self._reads = reads

    def check(self, request: PermissionCheck) -> PermissionDecision:
        source_system = request.call.source_system
        if request.call.action_class == ToolActionClass.CREATE:
            return self._check_container(request, source_system)
        return self._check_resource(request, source_system)

    def _check_resource(
        self,
        request: PermissionCheck,
        source_system: SourceSystem,
    ) -> PermissionDecision:
        if not request.resource_id:
            return self._deny(UNSUPPORTED)
        read = _read_for_resource(source_system, request.resource_id)
        if read is None:
            return self._deny(UNSUPPORTED)
        result = self._read(read, request.context)
        if result is None:
            return self._deny(UNREADABLE)

        current = source_version_of(source_system, _payload_of(result))
        if current is None:
            # The read succeeded but stated no version. Refused rather than waved
            # through: a resource whose version cannot be read cannot be shown not
            # to have moved, and "we could not tell" must never mean "go ahead".
            return self._deny(UNSUPPORTED)
        if current != request.expected_resource_version:
            return self._deny(CHANGED)
        return PermissionDecision(allowed=True, decision_id="source-read")

    def _check_container(
        self,
        request: PermissionCheck,
        source_system: SourceSystem,
    ) -> PermissionDecision:
        if not request.container_id:
            return self._deny(UNSUPPORTED)
        read = _read_for_container(source_system)
        if read is None:
            return self._deny(UNSUPPORTED)
        result = self._read(read, request.context)
        if result is None:
            return self._deny(UNREADABLE)
        if request.container_id not in _identifiers_in(_payload_of(result)):
            return self._deny(UNREADABLE)
        return PermissionDecision(allowed=True, decision_id="source-read")

    @staticmethod
    def _deny(reason_code: str) -> PermissionDecision:
        """Every refusal carries the same decision id, and only the code varies.

        The id names which verifier spoke; the code names what it found. Keeping
        them separate means a caller can act on the reason -- re-propose after a
        change, seek access after a denial -- without parsing an identifier.
        """

        return PermissionDecision(
            allowed=False, decision_id="source-read", reason_code=reason_code
        )

    def _read(self, call: MCPReadToolCall, context: SecurityContext) -> Any:
        """Run one async read from this synchronous caller, or report failure.

        The runner is synchronous and the read pipeline is not. Inside a FastAPI
        sync route the call arrives on a worker thread anyio started, so the running
        loop can be borrowed; the fallback covers a plain synchronous caller with no
        loop to borrow, where a private one is correct because a permission check is
        rare and short.
        """

        async def run() -> Any:
            return await self._reads.execute_call(call=call, context=context)

        try:
            try:
                return anyio.from_thread.run(run)
            except RuntimeError:
                return anyio.run(run)
        except MCPReadError:
            # Every read failure is one answer: the target could not be confirmed, so
            # the write does not happen. Which failure it was belongs in the read's
            # own audit entry, not in a decision the caller could act on.
            return None


__all__ = [
    "CHANGED",
    "UNREADABLE",
    "UNSUPPORTED",
    "SourceReadPermissionVerifier",
    "source_version_of",
]
