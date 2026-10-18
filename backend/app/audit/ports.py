from typing import Protocol

from app.audit.domain import AuditChange, AuditEvent


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class AuditTrail(Protocol):
    """Relire la piste, pour la montrer a qui elle concerne.

    Separe de l'ecriture, et pas seulement par gout : un sink est passe a tout ce
    qui doit tracer -- le chemin de lecture, l'atelier d'approbation, le fournisseur
    de modele. Leur donner la lecture en meme temps donnerait a chacun le moyen de
    parcourir la piste des autres, alors qu'aucun n'en a besoin.

    Le tenant n'est pas un filtre parmi d'autres : c'est la portee. Un appelant qui
    pourrait l'elargir lirait la piste d'un autre client.
    """

    def recent(
        self,
        *,
        tenant_id: str,
        event_types: tuple[str, ...],
        limit: int,
    ) -> tuple[AuditChange, ...]: ...
