from threading import RLock
from typing import Any

from app.audit.domain import AuditEvent


class InMemoryAuditSink:
    """Development-only audit sink. It is not a compliant durable audit log."""

    def __init__(self, *, lock: Any | None = None) -> None:
        self._events: list[AuditEvent] = []
        self._lock = lock if lock is not None else RLock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def recent(
        self,
        *,
        tenant_id: str,
        event_types: tuple[str, ...],
        limit: int,
    ) -> tuple[AuditEvent, ...]:
        """La meme lecture que l'adaptateur durable, pour que les deux se comportent
        pareil : borne au tenant, filtree, la plus recente en tete."""

        with self._lock:
            retenus = [
                event
                for event in self._events
                if event.tenant_id == tenant_id
                and (not event_types or event.event_type.value in event_types)
            ]
        retenus.sort(key=lambda event: event.occurred_at, reverse=True)
        return tuple(retenus[:limit])

    def snapshot(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def _restore(self, events: tuple[AuditEvent, ...]) -> None:
        with self._lock:
            self._events = list(events)
