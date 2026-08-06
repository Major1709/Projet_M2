from threading import RLock

from app.audit.domain import AuditEvent


class InMemoryAuditSink:
    """Development-only audit sink. It is not a compliant durable audit log."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = RLock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)
