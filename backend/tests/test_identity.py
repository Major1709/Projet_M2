from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_container
from app.core.config import Settings
from app.core.identity import SUPPORTED_AUTH_MODE
from app.main import create_app

SOME_CONVERSATION = "/api/conversations/11111111-1111-4111-8111-111111111111"


def client_for(auth_mode: str | None) -> TestClient:
    settings = Settings(environment="test")
    container = build_container(settings)
    if auth_mode is not None and auth_mode != settings.auth_mode:
        # Settings only admits one mode today, so the future state is simulated by
        # replacing the value the request path reads. That is exactly the change a
        # deployment would make when a second mode is implemented.
        container = replace(
            container,
            settings=settings.model_copy(update={"auth_mode": auth_mode}),
        )
    return TestClient(create_app(settings, container))


def test_the_declared_mode_lets_the_derived_identity_through() -> None:
    # Asserting "not 500" would pass on a 404 and prove nothing. The identity has
    # to be shown reaching the workflow: the owner sees the conversation, and a
    # different user under the same tenant does not.
    client = client_for(SUPPORTED_AUTH_MODE)
    owner = {"X-Tenant-ID": "tenant-a", "X-User-ID": "owner"}

    created = client.post("/api/conversations", headers=owner, json={"title": "Suivi Jira"})
    assert created.status_code == 201
    conversation = f"/api/conversations/{created.json()['id']}"

    assert client.get(conversation, headers=owner).status_code == 200
    assert (
        client.get(
            conversation,
            headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "someone-else"},
        ).status_code
        == 404
    )


def test_an_unimplemented_identity_mode_refuses_the_request() -> None:
    # The settings already forbid production while the mode is dev_headers, but
    # that check is far from the risk: adding a mode would make production
    # constructible while every route kept trusting the headers, and the audit
    # trail would then record a tenant the caller chose. The request path has to
    # refuse on its own.
    response = client_for("oidc").get(SOME_CONVERSATION)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "IDENTITY_MODE_UNSUPPORTED"


def test_the_refusal_does_not_depend_on_the_headers_sent() -> None:
    # Otherwise a caller could reach the fallback by omitting or forging them.
    response = client_for("oidc").get(
        SOME_CONVERSATION,
        headers={"X-Tenant-ID": "tenant-victime", "X-User-ID": "admin"},
    )

    assert response.status_code == 500
