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

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.mcp.domain import MCPReadProvenance, MCPReadResult, MCPReadSourceSystem


class AgentSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_system: MCPReadSourceSystem
    tool_name: str
    # ``None`` for a read that enumerates rather than designates -- a project list,
    # a search. Inventing a link for one would cite a page nobody read.
    url: str | None = None
    # Le nom que la personne reconnaitrait : "CDCF K20", "KAN-39 - Suivi de projet".
    #
    # L'ecran citait le nom de l'outil -- "getConfluencePage" -- qui dit comment la
    # lecture a ete faite et jamais ce qui a ete lu. Un lecteur ne peut pas verifier
    # une source qu'il ne sait pas nommer.
    #
    # Absent quand la lecture ne designe rien, une recherche par exemple : lui donner
    # le titre de son premier resultat laisserait croire qu'une seule page a ete
    # consultee.
    title: str | None = None
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
    title: str | None = None


# Un titre long n'aide personne dans une liste de sources, et un resume de ticket
# peut faire une phrase entiere.
MAX_TITLE_LENGTH = 120


def _payload_of(result: MCPReadResult) -> dict[str, Any] | None:
    """La charge rendue par la lecture, quelle que soit la facon dont elle arrive.

    Les serveurs Atlassian rendent du JSON dans un bloc de texte ; l'adaptateur Figma
    rend une charge structuree. Les deux chemins sont lus ici plutot qu'a deux
    endroits qui finiraient par diverger.
    """

    if isinstance(result.structured_content, dict):
        return result.structured_content
    for block in result.content:
        texte = getattr(block, "text", None)
        if not isinstance(texte, str):
            continue
        try:
            charge = json.loads(texte)
        except (ValueError, RecursionError):
            # Une lecture qui ne rend pas du JSON n'est pas une anomalie : elle n'a
            # simplement pas de titre a offrir.
            continue
        if isinstance(charge, dict):
            return charge
    return None


def _trimmed(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    texte = " ".join(value.split())
    if not texte:
        return None
    return texte[:MAX_TITLE_LENGTH]


def title_of(result: MCPReadResult) -> str | None:
    """Le nom sous lequel la personne reconnaitrait ce qui a ete lu.

    Tire de la charge et non devine : un titre invente ferait cliquer vers une page
    dont le nom ne correspond pas. Rien n'est rendu quand la charge ne le porte pas.

    Seules les lectures qui designent une ressource en recoivent un -- celles-la
    seules portent un ``resource_reference``. Une recherche nommee d'apres son
    premier resultat laisserait croire qu'une seule page a ete consultee.
    """

    if result.provenance.resource_reference is None:
        return None
    charge = _payload_of(result)
    if charge is None:
        return None

    systeme = result.provenance.source_system
    if systeme is MCPReadSourceSystem.CONFLUENCE:
        return _trimmed(charge.get("title"))
    if systeme is MCPReadSourceSystem.JIRA:
        cle = _trimmed(charge.get("key"))
        champs = charge.get("fields")
        resume = _trimmed(champs.get("summary")) if isinstance(champs, dict) else None
        if cle and resume:
            return _trimmed(f"{cle} - {resume}")
        return cle or resume
    if systeme is MCPReadSourceSystem.FIGMA:
        fichier = charge.get("file")
        if isinstance(fichier, dict):
            return _trimmed(fichier.get("name"))
        return _trimmed(charge.get("name"))
    return None


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
                title=record.title,
            )
            continue
        changes: dict[str, Any] = {}
        if record.truncated and not existing.truncated:
            changes["truncated"] = True
        # Un titre peut etre ajoute, jamais remplace : la premiere lecture reste celle
        # qui nomme la source, et une seconde ne doit pas la renommer sous le lecteur.
        if existing.title is None and record.title is not None:
            changes["title"] = record.title
        if changes:
            seen[key] = existing.model_copy(update=changes)
    return tuple(seen.values())
