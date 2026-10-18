from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.audit.domain import AuditChange, AuditEvent
from app.persistence.schema import action_proposals, audit_events


class PostgresAuditSink:
    """Appends audit events through the approval transaction's Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: AuditEvent) -> None:
        self._session.execute(
            insert(audit_events).values(
                tenant_id=event.tenant_id,
                id=event.id,
                event_type=event.event_type.value,
                actor_user_id=event.actor_user_id,
                correlation_id=event.correlation_id,
                action_proposal_id=event.action_proposal_id,
                details=event.model_dump(mode="json")["details"],
                occurred_at=event.occurred_at,
            )
        )


class PostgresAppendOnlyAuditWriter:
    """Persists one event per short autonomous transaction, never around I/O."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def append(self, event: AuditEvent) -> None:
        with self._session_factory.begin() as session:
            PostgresAuditSink(session).append(event)


class PostgresAuditTrail:
    """Relit la piste, bornee au tenant de la session.

    Sa propre classe plutot qu'une methode de plus sur l'ecrivain : le sink est
    passe au chemin de lecture, a l'atelier d'approbation et au fournisseur de
    modele, et aucun d'eux n'a besoin de parcourir la piste. Separer, c'est refuser
    a chacun un pouvoir qu'il n'utilise pas.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def recent(
        self,
        *,
        tenant_id: str,
        event_types: tuple[str, ...],
        limit: int,
    ) -> tuple[AuditChange, ...]:
        """Les evenements, et la ressource que chacun touchait.

        La ressource est jointe depuis la proposition plutot que recopiee dans les
        details au moment de l'ecriture. Deux raisons : les evenements deja
        enregistres redeviennent lisibles sans migration, et la piste ne duplique pas
        une verite dont le proprietaire est ailleurs -- une page renommee se lit
        renommee, ce qui est ce qu'on veut d'un historique qui sert a retrouver.

        Jointure externe : un evenement qui ne porte pas de proposition reste dans la
        liste, sous son seul libelle. Le perdre serait pire que de l'afficher nu.
        """

        cible = action_proposals.c.target
        statement = (
            select(
                audit_events,
                cible["title"].as_string().label("resource_title"),
                cible["resource_type"].as_string().label("resource_type"),
            )
            .select_from(
                audit_events.outerjoin(
                    action_proposals,
                    (audit_events.c.tenant_id == action_proposals.c.tenant_id)
                    & (audit_events.c.action_proposal_id == action_proposals.c.id),
                )
            )
            .where(audit_events.c.tenant_id == tenant_id)
        )
        if event_types:
            statement = statement.where(audit_events.c.event_type.in_(event_types))
        statement = statement.order_by(audit_events.c.occurred_at.desc()).limit(limit)
        with self._session_factory() as session:
            lignes = session.execute(statement).mappings().all()
        return tuple(
            AuditChange(
                event=AuditEvent.model_validate(
                    {
                        cle: valeur
                        for cle, valeur in dict(ligne).items()
                        if cle not in {"resource_title", "resource_type"}
                    }
                ),
                resource_title=ligne["resource_title"],
                resource_type=ligne["resource_type"],
            )
            for ligne in lignes
        )
