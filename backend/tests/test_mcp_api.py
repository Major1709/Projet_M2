from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.mcp.api import get_read_workflow
from app.mcp.domain import MCPReadBatchResult
from app.mcp.errors import MCPGrantUnavailable


def test_mcp_api_is_default_deny() -> None:
    client = TestClient(create_app(Settings(environment="test")))

    response = client.post(
        "/api/mcp/reads",
        json={
            "calls": [
                {
                    "source_system": "figma",
                    "tool_name": "getFigmaFile",
                    "arguments": {},
                }
            ]
        },
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "MCP_PROVIDER_DISABLED",
            "message": "The requested MCP provider is disabled",
        }
    }


def test_mcp_api_refuses_unknown_tool_and_extra_request_fields() -> None:
    settings = Settings(environment="test")
    client = TestClient(create_app(settings))

    unknown = client.post(
        "/api/mcp/reads",
        json={
            "calls": [
                {
                    "source_system": "figma",
                    "tool_name": "use_figma",
                    "arguments": {},
                }
            ]
        },
    )
    malformed = client.post(
        "/api/mcp/reads",
        json={
            "calls": [
                {
                    "source_system": "figma",
                    "tool_name": "getFigmaFile",
                    "arguments": {},
                    "endpoint": "https://attacker.invalid/mcp",
                }
            ]
        },
    )

    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "MCP_TOOL_DENIED"
    assert malformed.status_code == 422


def test_mcp_api_enforces_three_calls_per_turn() -> None:
    client = TestClient(create_app(Settings(environment="test")))
    call = {"source_system": "figma", "tool_name": "getFigmaFile", "arguments": {}}

    response = client.post("/api/mcp/reads", json={"calls": [call, call, call, call]})

    assert response.status_code == 422


def test_missing_development_secret_is_expurgated_from_api(tmp_path: Path) -> None:
    secret_path = tmp_path / "never-expose-this-secret-path"

    class UnavailableGrantWorkflow:
        async def execute_batch(self, batch: object, context: object) -> MCPReadBatchResult:
            del batch, context
            raise MCPGrantUnavailable()

    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_read_workflow] = UnavailableGrantWorkflow
    client = TestClient(app)

    response = client.post(
        "/api/mcp/reads",
        headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "user-a"},
        json={
            "calls": [
                {
                    "source_system": "figma",
                    "tool_name": "getFigmaFile",
                    "arguments": {},
                }
            ]
        },
    )

    assert response.status_code == 503
    serialized = response.text
    assert str(secret_path) not in serialized
    assert response.json()["detail"]["code"] == "MCP_GRANT_UNAVAILABLE"


def test_async_mcp_api_returns_workflow_result() -> None:
    class StubWorkflow:
        async def execute_batch(self, batch: object, context: object) -> MCPReadBatchResult:
            assert batch is not None
            assert context is not None
            return MCPReadBatchResult(results=())

    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_read_workflow] = StubWorkflow
    client = TestClient(app)

    response = client.post(
        "/api/mcp/reads",
        json={
            "calls": [
                {
                    "source_system": "figma",
                    "tool_name": "getFigmaFile",
                    "arguments": {},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {"results": []}
