"""L'historique des changements, tel qu'une interface le montre.

La piste d'audit enregistre tout : chaque lecture MCP, chaque appel au modele, chaque
proposition d'ecriture et son sort. Tout montrer noierait ce que la personne est venue
chercher -- « qu'est-ce qui a ete ecrit, et par qui ? » -- sous des centaines de
lignes de lectures. L'historique ne retient donc que les evenements qui CHANGENT
quelque chose, ce que son titre annonce deja.

Les details restent choisis champ par champ. ``details`` est un objet JSON libre,
alimente par du code interne qui n'a jamais promis de le rendre a un navigateur : le
deverser exposerait des empreintes, des cles d'idempotence et ce que quelqu'un y
ajoutera demain sans penser a cet ecran.
"""

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from app.audit.domain import AuditEvent, AuditEventType
from app.core.errors import IDENTITY_RESPONSES, responses_for
from app.core.identity import SecurityContext, get_security_context

router = APIRouter(prefix="/api/audit", tags=["audit"])

# Ce qui compte comme un changement. Les lectures et les appels au modele sont dans
# la piste et n'en font pas partie : ils n'ont rien modifie nulle part.
CHANGE_EVENTS: Final[tuple[str, ...]] = (
    AuditEventType.ACTION_PROPOSED.value,
    AuditEventType.ACTION_APPROVED.value,
    AuditEventType.ACTION_REJECTED.value,
    AuditEventType.ACTION_REVISED.value,
    AuditEventType.MUTATION_DISPATCHED.value,
    AuditEventType.MUTATION_EXECUTED.value,
    AuditEventType.MUTATION_FAILED.value,
)

DEFAULT_LIMIT: Final[int] = 50
MAX_LIMIT: Final[int] = 200


class AuditEventView(BaseModel):
    """Un changement, reduit a ce qu'un ecran doit en dire."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    event_type: str
    occurred_at: str
    # Ce qui relie les evenements d'une meme ecriture : proposee, approuvee, ecrite.
    action_proposal_id: UUID | None = None
    source_system: str | None = None
    tool_name: str | None = None
    action_class: str | None = None
    # La cle Jira ou l'identifiant de page reellement crees. C'est la seule chose que
    # la personne peut aller verifier elle-meme.
    external_ids: tuple[str, ...] = ()


class AuditPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[AuditEventView, ...]


def _text(details: dict[str, Any], key: str) -> str | None:
    value = details.get(key)
    return str(value) if isinstance(value, str | int) and str(value) else None


def _view(event: AuditEvent) -> AuditEventView:
    details = event.model_dump(mode="json").get("details") or {}
    if not isinstance(details, dict):
        details = {}
    identifiants = details.get("external_ids")
    return AuditEventView(
        id=event.id,
        event_type=event.event_type.value,
        occurred_at=event.occurred_at.isoformat(),
        action_proposal_id=event.action_proposal_id,
        source_system=_text(details, "source_system"),
        tool_name=_text(details, "tool_name"),
        action_class=_text(details, "action_class"),
        external_ids=(
            tuple(str(i) for i in identifiants if isinstance(i, str))
            if isinstance(identifiants, list)
            else ()
        ),
    )


@router.get(
    "/events",
    response_model=AuditPage,
    responses=responses_for((), *IDENTITY_RESPONSES),
)
def recent_changes(
    request: Request,
    context: Annotated[SecurityContext, Depends(get_security_context)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AuditPage:
    """Les derniers changements de ce tenant, les plus recents en tete.

    Le tenant vient de la session et jamais de la requete. Un appelant qui pourrait
    le choisir lirait la piste d'un autre client -- et une piste d'audit est
    precisement ce qu'on ne prete pas.
    """

    trail = getattr(request.app.state.container, "audit_trail", None)
    if trail is None:
        # Un deploiement dont la piste n'est pas relisible. Le dire franchement vaut
        # mieux que rendre une liste vide, qu'on lirait comme « rien ne s'est passe ».
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AUDIT_TRAIL_UNAVAILABLE",
                "message": "The audit trail cannot be read on this deployment",
            },
        )
    evenements = trail.recent(
        tenant_id=context.tenant_id,
        event_types=CHANGE_EVENTS,
        limit=limit,
    )
    return AuditPage(events=tuple(_view(event) for event in evenements))
