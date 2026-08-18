"""CORS is what lets the browser front end reach this API at all -- and what a
hostile page would need in order to reach it with headers of its own choosing.

The identity headers are the tenant here, so an origin allowed to send them is an
origin allowed to pick one. These tests hold the two ends: nothing is granted
unless a front end has been named, and what is granted is exact.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

ALLOWED = "http://localhost:3000"


def client_for(*origins: str) -> TestClient:
    settings = Settings(environment="test", frontend_origins=origins)
    return TestClient(create_app(settings))


def test_no_origin_is_granted_when_no_front_end_is_declared() -> None:
    response = client_for().get("/health", headers={"Origin": ALLOWED})

    assert "access-control-allow-origin" not in response.headers


def test_a_declared_origin_is_granted() -> None:
    response = client_for(ALLOWED).get("/health", headers={"Origin": ALLOWED})

    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_another_origin_is_not_granted() -> None:
    response = client_for(ALLOWED).get("/health", headers={"Origin": "http://localhost:3001"})

    assert "access-control-allow-origin" not in response.headers


def test_the_preflight_admits_the_identity_headers_the_gateway_sends() -> None:
    # Without these the browser refuses the POST before it is ever sent, and the
    # failure looks like a backend outage rather than a configuration gap.
    response = client_for(ALLOWED).options(
        "/api/agent/questions",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-tenant-id,x-user-id",
        },
    )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert {"content-type", "x-tenant-id", "x-user-id"} <= set(allowed.split(", "))


def test_credentials_are_never_allowed() -> None:
    response = client_for(ALLOWED).get("/health", headers={"Origin": ALLOWED})

    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://evil.test",  # plain HTTP off the developer's machine
        "https://app.test/assistant",  # a path is not an origin
        "https://app.test/",
        "ftp://app.test",
        "app.test",
    ],
)
def test_an_origin_that_is_not_an_exact_safe_origin_is_refused(origin: str) -> None:
    # Refused at construction: a wildcard accepted here would be discovered only by
    # noticing that a page nobody deployed can call the API with its own tenant.
    with pytest.raises(ValidationError):
        Settings(environment="test", frontend_origins=(origin,))


def test_a_local_https_front_end_is_accepted() -> None:
    settings = Settings(environment="test", frontend_origins=("https://app.test",))

    assert settings.frontend_origins == ("https://app.test",)
