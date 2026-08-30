import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Text, cast, func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.approvals.adapters.postgres import PostgresApprovalUnitOfWorkFactory
from app.approvals.domain import (
    ActionProposalCreate,
    ActionProposalState,
    ActionTarget,
    sha256_text,
)
from app.approvals.errors import VersionConflict
from app.approvals.workflow import ApprovalWorkflow
from app.audit.domain import AuditEvent, AuditEventType
from app.bootstrap import ApplicationContainer, build_container
from app.conversations.adapters.postgres import PostgresConversationRepository
from app.conversations.domain import Conversation, ConversationCreate
from app.core.config import Settings
from app.core.database import create_database_engine, create_session_factory
from app.core.identity import SecurityContext
from app.main import create_app
from app.mcp.domain import SourceSystem, ToolActionClass
from app.persistence.schema import action_proposals, audit_events

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_settings() -> Settings:
    if os.getenv("PKA_REPOSITORY_BACKEND", "").lower() != "postgres":
        pytest.skip("PostgreSQL integration settings are not enabled")
    return Settings()


@pytest.fixture(scope="module")
def postgres_engine(postgres_settings: Settings) -> Iterator[Engine]:
    engine = create_database_engine(postgres_settings)
    yield engine
    engine.dispose()


class StubToolPin:
    """Stands in for the mutation registry, which does not exist yet: the production
    adapter denies every tool by design, so these tests supply a fixed fingerprint."""

    def schema_sha256(self, *, source_system, tool_name) -> str:
        del source_system, tool_name
        return "a" * 64

def unique_context(label: str) -> SecurityContext:
    run_id = uuid4().hex
    return SecurityContext(
        tenant_id=f"integration-{label}-{run_id}",
        user_id=f"user-{run_id}",
    )


def proposal_command(conversation_id: UUID, correlation_id: str) -> ActionProposalCreate:
    return ActionProposalCreate(
        conversation_id=conversation_id,
        source_system=SourceSystem.CONFLUENCE,
        tool_name="confluence.create_page",
        action_class=ToolActionClass.CREATE,
        target=ActionTarget(
            source_system=SourceSystem.CONFLUENCE,
            resource_type="page",
            container_id="INTEGRATION-SPACE",
            title="Synthetic integration proposal",
        ),
        payload={"title": "Synthetic integration proposal", "body": "Synthetic only"},
        correlation_id=correlation_id,
    )


def dispose_container(container: ApplicationContainer) -> None:
    if container.engine is not None:
        container.engine.dispose()


def test_migration_is_current_and_schema_has_no_raw_token(postgres_engine: Engine) -> None:
    alembic_config = Path(__file__).resolve().parents[1] / "alembic.ini"
    script = ScriptDirectory.from_config(Config(str(alembic_config)))
    expected_head = script.get_current_head()
    with postgres_engine.connect() as connection:
        installed_revisions = set(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )

    assert installed_revisions == {expected_head}
    inspector = inspect(postgres_engine)
    assert {"conversations", "action_proposals", "audit_events"}.issubset(
        inspector.get_table_names()
    )
    proposal_columns = {column["name"] for column in inspector.get_columns("action_proposals")}
    assert "decision_token_hash" in proposal_columns
    assert "decision_token" not in proposal_columns


def test_vector_extension_is_installed_when_catalog_is_accessible(
    postgres_engine: Engine,
) -> None:
    try:
        with postgres_engine.connect() as connection:
            vector_installed = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            ).scalar_one()
    except SQLAlchemyError:
        pytest.skip("PostgreSQL extension catalog is not accessible")
    assert vector_installed is True


def test_round_trip_audit_persistence_isolation_and_one_time_token(
    postgres_settings: Settings,
) -> None:
    context = unique_context("roundtrip")
    first_container = build_container(postgres_settings)
    try:
        conversation = first_container.conversations.create(
            ConversationCreate(title="Synthetic persistent conversation"),
            context,
        )
        issued = first_container.approvals.propose(
            proposal_command(conversation.id, f"integration-{uuid4().hex}"),
            context,
        )
        assert first_container.engine is not None
        with first_container.engine.connect() as connection:
            stored_hash = connection.execute(
                select(action_proposals.c.decision_token_hash).where(
                    action_proposals.c.tenant_id == context.tenant_id,
                    action_proposals.c.id == issued.proposal.id,
                )
            ).scalar_one()
            raw_token_matches = connection.execute(
                select(func.count())
                .select_from(action_proposals)
                .where(
                    action_proposals.c.tenant_id == context.tenant_id,
                    action_proposals.c.id == issued.proposal.id,
                    or_(
                        cast(action_proposals.c.target, Text).contains(
                            issued.decision_token
                        ),
                        action_proposals.c.payload_json == issued.decision_token,
                        action_proposals.c.diff_json == issued.decision_token,
                        action_proposals.c.explanation == issued.decision_token,
                        action_proposals.c.correlation_id == issued.decision_token,
                        action_proposals.c.decision_token_hash == issued.decision_token,
                    ),
                )
            ).scalar_one()
            audit_token_matches = connection.execute(
                select(func.count())
                .select_from(audit_events)
                .where(
                    audit_events.c.tenant_id == context.tenant_id,
                    audit_events.c.action_proposal_id == issued.proposal.id,
                    cast(audit_events.c.details, Text).contains(issued.decision_token),
                )
            ).scalar_one()
            audit_count = connection.execute(
                select(func.count())
                .select_from(audit_events)
                .where(
                    audit_events.c.tenant_id == context.tenant_id,
                    audit_events.c.action_proposal_id == issued.proposal.id,
                )
            ).scalar_one()

        assert stored_hash == sha256_text(issued.decision_token)
        assert raw_token_matches == 0
        assert audit_token_matches == 0
        assert audit_count == 1

        app = create_app(postgres_settings, first_container)
        with TestClient(app) as client:
            owner_headers = {
                "X-Tenant-ID": context.tenant_id,
                "X-User-ID": context.user_id,
            }
            response = client.get(
                f"/api/actions/{issued.proposal.id}",
                headers=owner_headers,
            )
            assert response.status_code == 200
            assert "decision_token" not in response.json()
            assert "decision_token_hash" not in response.json()

            other_user = client.get(
                f"/api/actions/{issued.proposal.id}",
                headers={"X-Tenant-ID": context.tenant_id, "X-User-ID": "other-user"},
            )
            other_tenant = client.get(
                f"/api/actions/{issued.proposal.id}",
                headers={"X-Tenant-ID": "other-tenant", "X-User-ID": context.user_id},
            )
            other_conversation_user = client.get(
                f"/api/conversations/{conversation.id}",
                headers={"X-Tenant-ID": context.tenant_id, "X-User-ID": "other-user"},
            )
            other_conversation_tenant = client.get(
                f"/api/conversations/{conversation.id}",
                headers={"X-Tenant-ID": "other-tenant", "X-User-ID": context.user_id},
            )
            assert other_user.status_code == 404
            assert other_tenant.status_code == 404
            assert other_conversation_user.status_code == 404
            assert other_conversation_tenant.status_code == 404
    finally:
        dispose_container(first_container)

    reconstructed = build_container(postgres_settings)
    try:
        assert reconstructed.conversations.get(conversation.id, context).id == conversation.id
        assert reconstructed.approvals.get(issued.proposal.id, context).id == issued.proposal.id
    finally:
        dispose_container(reconstructed)


def test_compare_and_swap_allows_only_one_winner(postgres_engine: Engine) -> None:
    sessions = create_session_factory(postgres_engine)
    conversations = PostgresConversationRepository(sessions)
    unit_of_work_factory = PostgresApprovalUnitOfWorkFactory(sessions)
    workflow = ApprovalWorkflow(unit_of_work_factory, conversations, StubToolPin(), 900)
    context = unique_context("cas")
    conversation_record = Conversation(
        tenant_id=context.tenant_id,
        owner_user_id=context.user_id,
        title="Synthetic CAS conversation",
    )
    conversations.add(conversation_record)
    proposal = workflow.propose(
        proposal_command(conversation_record.id, f"integration-{uuid4().hex}"),
        context,
    ).proposal
    winner = proposal.model_copy(
        update={
            "state": ActionProposalState.REJECTED,
            "version": 2,
            "decision_token_hash": None,
            "updated_at": datetime.now(UTC),
        }
    )
    loser = proposal.model_copy(
        update={
            "state": ActionProposalState.APPROVED,
            "version": 2,
            "decision_token_hash": None,
            "updated_at": datetime.now(UTC),
        }
    )

    with unit_of_work_factory() as transaction:
        transaction.proposals.replace(proposal=winner, expected_version=1)
        transaction.commit()

    with pytest.raises(VersionConflict), unit_of_work_factory() as transaction:
        transaction.proposals.replace(proposal=loser, expected_version=1)
        transaction.commit()

    assert workflow.get(proposal.id, context).state == ActionProposalState.REJECTED


def test_audit_failure_rolls_back_proposal_transition(postgres_engine: Engine) -> None:
    sessions = create_session_factory(postgres_engine)
    conversations = PostgresConversationRepository(sessions)
    unit_of_work_factory = PostgresApprovalUnitOfWorkFactory(sessions)
    workflow = ApprovalWorkflow(unit_of_work_factory, conversations, StubToolPin(), 900)
    context = unique_context("rollback")
    conversation = Conversation(
        tenant_id=context.tenant_id,
        owner_user_id=context.user_id,
        title="Synthetic rollback conversation",
    )
    conversations.add(conversation)
    proposal = workflow.propose(
        proposal_command(conversation.id, f"integration-{uuid4().hex}"),
        context,
    ).proposal
    duplicate_audit = AuditEvent(
        event_type=AuditEventType.ACTION_REJECTED,
        tenant_id=context.tenant_id,
        actor_user_id=context.user_id,
        correlation_id=proposal.correlation_id,
        action_proposal_id=proposal.id,
        details={"synthetic": True},
    )
    with unit_of_work_factory() as transaction:
        transaction.audit.append(duplicate_audit)
        transaction.commit()

    transition = proposal.model_copy(
        update={
            "state": ActionProposalState.REJECTED,
            "version": 2,
            "decision_token_hash": None,
            "updated_at": datetime.now(UTC),
        }
    )
    with pytest.raises(IntegrityError), unit_of_work_factory() as transaction:
        transaction.proposals.replace(proposal=transition, expected_version=1)
        transaction.audit.append(duplicate_audit)
        transaction.commit()

    persisted = workflow.get(proposal.id, context)
    assert persisted.version == 1
    assert persisted.state == ActionProposalState.PENDING_APPROVAL
