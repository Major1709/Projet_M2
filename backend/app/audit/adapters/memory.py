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

    def snapshot(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def _restore(self, events: tuple[AuditEvent, ...]) -> None:
        with self._lock:
            self._events = list(events)
