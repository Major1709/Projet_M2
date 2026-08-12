from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any

from sqlalchemy.sql.dml import Insert

from app.audit.adapters.postgres import PostgresAppendOnlyAuditWriter
from app.audit.domain import AuditEvent, AuditEventType


class FakeSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement: object) -> None:
        self.statements.append(statement)


class FakeTransaction(AbstractContextManager[FakeSession]):
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.exited_with: type[BaseException] | None = None

    def __enter__(self) -> FakeSession:
        return self.session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        self.exited_with = exc_type
        return False


class FakeSessionFactory:
    def __init__(self) -> None:
        self.session = FakeSession()
        self.transactions: list[FakeTransaction] = []

    def begin(self) -> FakeTransaction:
        transaction = FakeTransaction(self.session)
        self.transactions.append(transaction)
        return transaction


def test_postgres_audit_writer_uses_one_short_insert_only_transaction() -> None:
    factory = FakeSessionFactory()
    writer = PostgresAppendOnlyAuditWriter(factory)  # type: ignore[arg-type]
    event = AuditEvent(
        event_type=AuditEventType.MCP_READ_AUTHORIZED,
        tenant_id="tenant-a",
        actor_user_id="user-a",
        correlation_id="corr-a",
        details={"provider": "figma", "tool_name": "whoami"},
    )

    writer.append(event)

    assert len(factory.transactions) == 1
    assert factory.transactions[0].exited_with is None
    assert len(factory.session.statements) == 1
    assert isinstance(factory.session.statements[0], Insert)
    assert factory.session.statements[0].table.name == "audit_events"  # type: ignore[union-attr]


def test_mcp_audit_event_details_reject_non_mapping_payload() -> None:
    invalid: dict[str, Any] = {"details": "never persist raw content"}

    try:
        AuditEvent(
            event_type=AuditEventType.MCP_READ_FAILED,
            tenant_id="tenant-a",
            actor_user_id="user-a",
            correlation_id="corr-a",
            **invalid,
        )
    except ValueError:
        return
    raise AssertionError("Audit details must remain a metadata mapping")
