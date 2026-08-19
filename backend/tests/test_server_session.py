from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient

from app.bootstrap import build_container
from app.core.config import Settings
from app.core.identity import DEV_HEADERS_MODE, SESSION_MODE
from app.main import create_app
from app.sessions.domain import (
    SESSION_COOKIE_NAME,
    Session,
    new_session_token,
    session_token_hash,
    utc_now,
)
from app.sessions.errors import SessionUnavailable

SOME_CONVERSATION = "/api/conversations/11111111-1111-4111-8111-111111111111"
# Headers a caller could always forge. In session mode they must change nothing.
FORGED = {"X-Tenant-ID": "tenant-victime", "X-User-ID": "admin"}


def app_for(auth_mode: str):
    settings = Settings(environment="test")
    container = build_container(settings)
    if auth_mode != settings.auth_mode:
        container = replace(
            container,
            settings=settings.model_copy(update={"auth_mode": auth_mode}),
        )
    return create_app(settings, container), container


def signed_in(
    container,
    *,
    tenant_id: str = "tenant-a",
    user_id: str = "owner",
    lifetime: timedelta = timedelta(hours=12),
) -> str:
    token = new_session_token()
    container.sessions.create(
        Session(
            token_hash=session_token_hash(token),
            tenant_id=tenant_id,
            user_id=user_id,
            expires_at=utc_now() + lifetime,
        )
    )
    return token


def test_no_cookie_means_no_identity() -> None:
    app, _ = app_for(SESSION_MODE)

    response = TestClient(app).get(SOME_CONVERSATION)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "IDENTITY_REQUIRED"


def test_the_identity_headers_are_inert_in_session_mode() -> None:
    # The whole point of the mode. A fallback to the headers would hand the tenant
    # straight back to the caller it was taken from.
    app, _ = app_for(SESSION_MODE)

    response = TestClient(app).get(SOME_CONVERSATION, headers=FORGED)

    assert response.status_code == 401


def test_the_session_decides_the_tenant_and_the_headers_do_not() -> None:
    # The strongest statement available: a caller presenting a valid session *and*
    # headers claiming to be someone else gets the session's identity. Proven by
    # what they can read afterwards, not by inspecting the context.
    app, container = app_for(SESSION_MODE)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, signed_in(container))

    created = client.post("/api/conversations", headers=FORGED, json={"title": "Suivi"})
    assert created.status_code == 201

    conversation = f"/api/conversations/{created.json()['id']}"
    assert client.get(conversation, headers=FORGED).status_code == 200

    # And the identity the forged headers named cannot reach it, even with a
    # perfectly valid session of its own.
    intruder = TestClient(app)
    intruder.cookies.set(
        SESSION_COOKIE_NAME,
        signed_in(container, tenant_id="tenant-victime", user_id="admin"),
    )
    assert intruder.get(conversation).status_code == 404


def test_an_expired_session_is_refused() -> None:
    app, container = app_for(SESSION_MODE)
    client = TestClient(app)
    token = new_session_token()
    container.sessions.create(
        Session(
            token_hash=session_token_hash(token),
            tenant_id="tenant-a",
            user_id="owner",
            created_at=utc_now() - timedelta(hours=13),
            expires_at=utc_now() - timedelta(minutes=1),
        )
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)

    response = client.get(SOME_CONVERSATION)

    # Same answer as an absent session, on purpose: telling a caller their session
    # existed but lapsed says something about a token they may not own.
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "IDENTITY_REQUIRED"


def test_a_revoked_session_stops_working_immediately() -> None:
    app, container = app_for(SESSION_MODE)
    client = TestClient(app)
    token = signed_in(container)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    assert client.get(SOME_CONVERSATION).status_code == 404

    container.sessions.revoke(session_token_hash(token))

    assert client.get(SOME_CONVERSATION).status_code == 401


def test_an_unknown_token_is_refused() -> None:
    app, _ = app_for(SESSION_MODE)
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, new_session_token())

    assert client.get(SOME_CONVERSATION).status_code == 401


def test_an_unreachable_store_refuses_rather_than_falls_back() -> None:
    # Fail closed. An identity that cannot be verified must not be asserted, and the
    # headers are sitting right there as a tempting fallback.
    app, container = app_for(SESSION_MODE)

    def unavailable(token_hash: str):
        raise SessionUnavailable()

    container.sessions.get_by_token_hash = unavailable  # type: ignore[method-assign]
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, new_session_token())

    response = client.get(SOME_CONVERSATION, headers=FORGED)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SESSION_STORE_UNAVAILABLE"


def test_the_token_is_never_held_in_clear() -> None:
    # A leaked store must not yield usable sessions.
    _, container = app_for(SESSION_MODE)
    token = signed_in(container)

    assert container.sessions.get_by_token_hash(token) is None
    stored = container.sessions.get_by_token_hash(session_token_hash(token))
    assert stored is not None
    assert token not in stored.model_dump_json()


def test_two_tokens_never_collide() -> None:
    assert len({new_session_token() for _ in range(500)}) == 500


def test_the_header_mode_still_works() -> None:
    # Regression guard: the second mode is additive, and the front end being
    # restyled in parallel still sends headers.
    app, _ = app_for(DEV_HEADERS_MODE)
    client = TestClient(app)
    owner = {"X-Tenant-ID": "tenant-a", "X-User-ID": "owner"}

    created = client.post("/api/conversations", headers=owner, json={"title": "Suivi"})

    assert created.status_code == 201
    conversation = f"/api/conversations/{created.json()['id']}"
    assert client.get(conversation, headers=owner).status_code == 200


def test_an_unimplemented_mode_still_fails_the_request() -> None:
    app, _ = app_for("kerberos")

    response = TestClient(app).get(SOME_CONVERSATION, headers=FORGED)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "IDENTITY_MODE_UNSUPPORTED"
