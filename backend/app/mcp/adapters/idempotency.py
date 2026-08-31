import json
import secrets
from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.mcp.domain import MCPExecutionResult
from app.mcp.ports import MutationReservation
from app.persistence.schema import mutation_idempotency

# 32 random bytes, URL-safe. Long enough that two reservations never collide by
# accident, and opaque so it carries nothing about the action it belongs to.
_KEY_BYTES = 32


def _mint() -> str:
    return secrets.token_urlsafe(_KEY_BYTES)


class InMemoryMutationIdempotencyStore:
    """Development-only store. Durable for the life of one process, and no longer."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, UUID], MutationReservation] = {}
        self._lock = RLock()

    def find(self, *, tenant_id: str, proposal_id: UUID) -> MutationReservation | None:
        with self._lock:
            return self._rows.get((tenant_id, proposal_id))

    def reserve(self, *, tenant_id: str, proposal_id: UUID) -> MutationReservation:
        with self._lock:
            existing = self._rows.get((tenant_id, proposal_id))
            if existing is not None:
                return existing
            reservation = MutationReservation(idempotency_key=_mint())
            self._rows[(tenant_id, proposal_id)] = reservation
            return reservation

    def record_outcome(
        self,
        *,
        tenant_id: str,
        proposal_id: UUID,
        result: MCPExecutionResult,
    ) -> None:
        with self._lock:
            existing = self._rows.get((tenant_id, proposal_id))
            if existing is None:
                raise ValueError("Cannot record an outcome for an unreserved mutation")
            self._rows[(tenant_id, proposal_id)] = MutationReservation(
                idempotency_key=existing.idempotency_key,
                completed=True,
                result=result,
            )


class PostgresMutationIdempotencyStore:
    """Durable reservation, committed on its own before the provider is contacted.

    It deliberately does not join the caller's transaction. A reservation rolled back
    alongside a failed mutation would be reminted on retry, and the provider would then
    see two distinct requests for one approved action -- the precise outcome an
    idempotency key exists to prevent. Committing separately means a reservation can
    outlive an action that never ran, which is the safe direction: the worst case is a
    key nobody spends.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def find(self, *, tenant_id: str, proposal_id: UUID) -> MutationReservation | None:
        with self._session_factory() as session:
            return self._read(session, tenant_id=tenant_id, proposal_id=proposal_id)

    def reserve(self, *, tenant_id: str, proposal_id: UUID) -> MutationReservation:
        with self._session_factory() as session:
            now = datetime.now(UTC)
            try:
                session.execute(
                    insert(mutation_idempotency).values(
                        tenant_id=tenant_id,
                        proposal_id=proposal_id,
                        idempotency_key=_mint(),
                        completed=False,
                        result_json=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.commit()
            except IntegrityError:
                # Someone reserved first -- a concurrent execution, or this one
                # retrying. Their key is the one that counts.
                session.rollback()
            reservation = self._read(session, tenant_id=tenant_id, proposal_id=proposal_id)
            if reservation is None:  # pragma: no cover - the insert above guarantees it
                raise ValueError("The reservation vanished between insert and read")
            return reservation

    def record_outcome(
        self,
        *,
        tenant_id: str,
        proposal_id: UUID,
        result: MCPExecutionResult,
    ) -> None:
        with self._session_factory() as session:
            outcome = session.execute(
                update(mutation_idempotency)
                .where(
                    mutation_idempotency.c.tenant_id == tenant_id,
                    mutation_idempotency.c.proposal_id == proposal_id,
                )
                .values(
                    completed=True,
                    result_json=result.model_dump_json(),
                    updated_at=datetime.now(UTC),
                )
            )
            if outcome.rowcount != 1:
                raise ValueError("Cannot record an outcome for an unreserved mutation")
            session.commit()

    @staticmethod
    def _read(session, *, tenant_id: str, proposal_id: UUID) -> MutationReservation | None:
        row = (
            session.execute(
                select(mutation_idempotency).where(
                    mutation_idempotency.c.tenant_id == tenant_id,
                    mutation_idempotency.c.proposal_id == proposal_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        raw_result = row["result_json"]
        return MutationReservation(
            idempotency_key=row["idempotency_key"],
            completed=row["completed"],
            result=(
                MCPExecutionResult.model_validate(json.loads(raw_result))
                if raw_result is not None
                else None
            ),
        )
