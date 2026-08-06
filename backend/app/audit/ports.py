from typing import Protocol

from app.audit.domain import AuditEvent


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...
