"""Turn read provenance into the sources an answer may claim.

Two rules decide everything here. A link is produced only when the read carried a
``resource_reference``, which the registry derives from a *required public
argument* and never reads back from a provider response -- so a citation cannot be
redirected by a compromised server, and a tool that designates no single resource
gets no link rather than a plausible-looking one.

The rest is a projection. The full provenance carries schema digests and a binding
fingerprint: internal facts that belong in the audit trail, not in an answer handed
to a caller. What a reader needs is where it came from, when, and whether it was
whole.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.mcp.domain import MCPReadProvenance, MCPReadSourceSystem


class AgentSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_system: MCPReadSourceSystem
    tool_name: str
    # ``None`` for a read that enumerates rather than designates -- a project list,
    # a search. Inventing a link for one would cite a page nobody read.
    url: str | None = None
    retrieved_at: datetime
    # True when our observation ceiling cut the content before the model saw it, so
    # a reader knows the answer was formed from a fragment.
    #
    # Provenance also carries ``source_complete``, and it is deliberately not
    # surfaced here: the read workflow always leaves it false, because no
    # authenticated output schema attests that a body is whole. A field that is
    # constant carries no information but reads like a signal, and "every source
    # incomplete" is a worse claim than saying nothing. It belongs in the audit
    # trail until a provider gives us something to derive it from.
    truncated: bool = False


class ReadRecord(BaseModel):
    """One performed read, as the loop observed it."""

    model_config = ConfigDict(frozen=True)

    provenance: MCPReadProvenance
    truncated: bool = False


def _identity(provenance: MCPReadProvenance) -> tuple[str, ...]:
    """What makes two reads the same source.

    A resource is identified by its reference alone: the same ticket read twice with
    different fields is one source, not two. A collection has no reference, so it is
    identified by the query that produced it -- the tool and the digest of its
    arguments -- which keeps two different searches apart while collapsing a repeat
    of the same one.
    """

    if provenance.resource_reference is not None:
        return ("resource", provenance.resource_reference)
    return ("collection", provenance.tool_name, provenance.arguments_sha256)


def sources_from(records: tuple[ReadRecord, ...]) -> tuple[AgentSource, ...]:
    """Project reads into deduplicated sources, in the order they were first read.

    First occurrence wins, so the order matches the order the assistant actually
    consulted them. A later repeat of the same source can only add flags, never
    remove them: a read that was truncated once is reported as truncated, because
    the model did see a fragment even if a later read was whole.
    """

    seen: dict[tuple[str, ...], AgentSource] = {}
    for record in records:
        key = _identity(record.provenance)
        existing = seen.get(key)
        if existing is None:
            seen[key] = AgentSource(
                source_system=record.provenance.source_system,
                tool_name=record.provenance.tool_name,
                url=record.provenance.resource_reference,
                retrieved_at=record.provenance.retrieved_at,
                truncated=record.truncated,
            )
            continue
        if record.truncated and not existing.truncated:
            seen[key] = existing.model_copy(update={"truncated": True})
    return tuple(seen.values())
