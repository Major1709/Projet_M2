from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def build_client() -> TestClient:
    return TestClient(create_app(Settings(environment="test")))


def test_health_endpoints_are_available() -> None:
    client = build_client()

    for path in ("/health", "/health/live", "/health/ready"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


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
