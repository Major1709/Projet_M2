from pathlib import Path
from time import monotonic

from fastapi.testclient import TestClient

from app.approvals.adapters.memory import InMemoryApprovalUnitOfWork
from app.approvals.api import get_workflow as get_approval_workflow
from app.approvals.workflow import ApprovalWorkflow
from app.conversations.adapters.memory import InMemoryConversationRepository
from app.conversations.domain import Conversation
from app.core.config import Settings
from app.core.identity import DEV_HEADERS_MODE
from app.main import create_app


class StubToolPin:
    """Stands in for the mutation registry, which does not exist yet: the production
    adapter denies every tool by design, so these tests supply a fixed fingerprint."""

    def schema_sha256(self, *, source_system, tool_name) -> str:
        del source_system, tool_name
        return "a" * 64

def build_client() -> TestClient:
    return TestClient(create_app(Settings(environment="test")))


def test_health_endpoints_are_available() -> None:
    client = build_client()

    for path in ("/health", "/health/live", "/health/ready"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_postgres_readiness_fails_closed_within_health_budget(tmp_path: Path) -> None:
    password_file = tmp_path / "postgres_password"
    password_file.write_text("synthetic-readiness-password\n", encoding="utf-8")
    settings = Settings(
        environment="test",
        repository_backend="postgres",
        database_host="192.0.2.1",
        database_port=5432,
        database_name="unreachable",
        database_user="readiness",
        database_password_file=password_file,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        started_at = monotonic()
        response = client.get("/health/ready")
        elapsed = monotonic() - started_at

    assert response.status_code == 503
    assert response.json() == {"detail": "Service is not ready"}
    assert elapsed < 3


def test_conversation_is_visible_only_to_its_owner() -> None:
    client = build_client()
    owner_headers = {"X-Tenant-ID": "tenant-a", "X-User-ID": "owner"}

    created = client.post(
        "/api/conversations",
        headers=owner_headers,
        json={"title": "Analyse des demandes Jira"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    visible = client.get(
        f"/api/conversations/{conversation_id}",
        headers=owner_headers,
    )
    assert visible.status_code == 200

    hidden = client.get(
        f"/api/conversations/{conversation_id}",
        headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "other-user"},
    )
    assert hidden.status_code == 404


def test_action_decision_token_is_returned_once_and_never_by_get() -> None:
    app = create_app(Settings(environment="test"))
    unit_of_work = InMemoryApprovalUnitOfWork()
    conversations = InMemoryConversationRepository()
    conversation = Conversation(
        tenant_id="tenant-a",
        owner_user_id="owner",
        title="Approval contract",
    )
    conversations.add(conversation)
    # dev_headers, matching the app under test: the route derives its identity from
    # headers here, so there is no session for the proposal to bind to.
    workflow = ApprovalWorkflow(
        unit_of_work, conversations, StubToolPin(), 900, DEV_HEADERS_MODE
    )
    app.dependency_overrides[get_approval_workflow] = lambda: workflow
    client = TestClient(app)
    headers = {"X-Tenant-ID": "tenant-a", "X-User-ID": "owner"}

    created = client.post(
        "/api/actions",
        headers=headers,
        json={
            "conversation_id": str(conversation.id),
            "source_system": "confluence",
            "tool_name": "confluence.create_page",
            "action_class": "CREATE",
            "target": {
                "source_system": "confluence",
                "resource_type": "page",
                "container_id": "SPACE-1",
                "title": "Epic paiement",
            },
            "payload": {"title": "Epic paiement", "body": "Version exacte"},
            "correlation_id": "corr-api-1",
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    token = created_body["decision_token"]
    assert "decision_token_hash" not in created_body

    fetched = client.get(f"/api/actions/{created_body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert "decision_token" not in fetched.json()
    assert "decision_token_hash" not in fetched.json()

    approved = client.post(
        f"/api/actions/{created_body['id']}/approve",
        headers=headers,
        json={"expected_version": 1, "decision_token": token},
    )
    assert approved.status_code == 200
    assert "decision_token" not in approved.json()
    assert "decision_token_hash" not in approved.json()
