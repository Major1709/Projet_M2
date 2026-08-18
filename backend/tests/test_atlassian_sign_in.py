import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.auth.client import AtlassianOAuthClient
from app.auth.domain import (
    ATLASSIAN_ACCESSIBLE_RESOURCES,
    ATLASSIAN_ME_ENDPOINT,
    ATLASSIAN_OAUTH_TOKEN_ENDPOINT,
    PendingAuthorization,
    code_challenge_for,
    new_code_verifier,
    utc_now,
)
from app.auth.errors import (
    AmbiguousSiteGrant,
    AuthorizationExpired,
    NoSiteGranted,
    ProviderRefused,
    UnexpectedSiteGranted,
)
from app.auth.workflow import AtlassianSignIn
from app.bootstrap import build_container
from app.core.config import Settings
from app.core.identity import SESSION_MODE
from app.main import create_app
from app.sessions.adapters.memory import InMemorySessionStore
from app.sessions.domain import SESSION_COOKIE_NAME, session_token_hash

ACCOUNT = "5f8a:abc-account"
CLOUD_ID = "a761589f-69b8-4373-9c30-7561c2d45a39"
SITE_URL = "https://example.atlassian.net"


@pytest.fixture
def anyio_backend() -> str:
    # One backend is enough here: nothing in this flow is loop-implementation
    # specific, and running every case twice would only slow the suite.
    return "asyncio"


class Recorder:
    """A transport standing in for Atlassian, remembering what it was sent."""

    def __init__(self, *, token_status: int = 200, resources: object | None = None):
        self.token_status = token_status
        self.resources = (
            [{"id": CLOUD_ID, "url": SITE_URL}] if resources is None else resources
        )
        self.token_form: dict[str, list[str]] = {}
        self.bearer_tokens: list[str] = []

    def transport(self) -> httpx2.MockTransport:
        async def handle(request: httpx2.Request) -> httpx2.Response:
            url = str(request.url)
            if url == ATLASSIAN_OAUTH_TOKEN_ENDPOINT:
                self.token_form = parse_qs(request.content.decode())
                if self.token_status != 200:
                    return httpx2.Response(self.token_status, json={"error": "invalid_grant"})
                return httpx2.Response(
                    200,
                    json={
                        "access_token": "at-secret",
                        "refresh_token": "rt-secret",
                        "expires_in": 3600,
                    },
                )
            self.bearer_tokens.append(request.headers.get("Authorization", ""))
            if url == ATLASSIAN_ACCESSIBLE_RESOURCES:
                return httpx2.Response(200, json=self.resources)
            if url == ATLASSIAN_ME_ENDPOINT:
                return httpx2.Response(200, json={"account_id": ACCOUNT})
            return httpx2.Response(404)

        return httpx2.MockTransport(handle)


def sign_in_for(recorder: Recorder, sessions=None, grants=None) -> AtlassianSignIn:
    from app.auth.adapters.memory import (
        InMemoryDelegatedGrantSink,
        InMemoryPendingAuthorizationStore,
    )

    return AtlassianSignIn(
        client=AtlassianOAuthClient(
            client_id="client-abc",
            client_secret="secret-xyz",
            redirect_uri="https://app.example/callback",
            transport=recorder.transport(),
        ),
        pending=InMemoryPendingAuthorizationStore(),
        sessions=sessions or InMemorySessionStore(),
        grants=grants or InMemoryDelegatedGrantSink(),
        client_id="client-abc",
        redirect_uri="https://app.example/callback",
        session_lifetime=timedelta(hours=12),
    )


def redeem(sign_in: AtlassianSignIn) -> tuple[str, str]:
    """Play the first leg, then hand back the state the provider would return."""

    url = sign_in.begin()
    state = parse_qs(urlsplit(url).query)["state"][0]
    return url, state


def test_the_authorization_url_asks_for_offline_access_and_a_fresh_consent() -> None:
    sign_in = sign_in_for(Recorder())

    url, _ = redeem(sign_in)
    query = parse_qs(urlsplit(url).query)

    assert urlsplit(url).netloc == "auth.atlassian.com"
    # Without offline_access the deployment is back at consent within the hour.
    assert "offline_access" in query["scope"][0]
    # Without prompt=consent Atlassian may reuse an earlier grant silently, and the
    # user never sees the site chooser that decides which site the token covers.
    assert query["prompt"] == ["consent"]
    assert query["audience"] == ["api.atlassian.com"]
    # An unguessable state is what actually ties the callback to this attempt.
    assert len(query["state"][0]) >= 32


def test_the_challenge_pair_is_well_formed_which_says_nothing_about_the_provider() -> None:
    # This asserts our own construction, not a guarantee from Atlassian: its 3LO
    # documentation does not describe code_challenge, and nothing here has observed
    # the provider rejecting a mismatched verifier. Treated as inert until seen to
    # work -- see docs/development-logs for the procedure that would settle it.
    sign_in = sign_in_for(Recorder())

    url, _ = redeem(sign_in)
    query = parse_qs(urlsplit(url).query)

    assert query["code_challenge_method"] == ["S256"]
    # Whatever the provider does with it, the verifier itself has no business being
    # in a URL that lands in browser history and server logs.
    assert "code_verifier" not in query


@pytest.mark.anyio
async def test_a_completed_sign_in_derives_the_tenant_from_the_provider() -> None:
    # The point of the whole slice: the tenant is read back from Atlassian, never
    # declared by the caller.
    recorder = Recorder()
    sessions = InMemorySessionStore()
    sign_in = sign_in_for(recorder, sessions=sessions)
    _, state = redeem(sign_in)

    token = await sign_in.complete(code="code-1", state=state)

    session = sessions.get_by_token_hash(session_token_hash(token))
    assert session is not None
    assert session.tenant_id == CLOUD_ID
    assert session.user_id == ACCOUNT


@pytest.mark.anyio
async def test_the_exchange_carries_the_secret_and_the_matching_verifier() -> None:
    recorder = Recorder()
    sign_in = sign_in_for(recorder)
    url, state = redeem(sign_in)

    await sign_in.complete(code="code-1", state=state)

    assert recorder.token_form["grant_type"] == ["authorization_code"]
    # The client secret is what Atlassian's documented flow actually authenticates
    # the exchange with, and it never leaves the server.
    assert recorder.token_form["client_secret"] == ["secret-xyz"]
    # The verifier we send matches the challenge we published. Our own consistency,
    # not a provider guarantee: see the note on code_challenge_for.
    sent = recorder.token_form["code_verifier"][0]
    assert code_challenge_for(sent) == parse_qs(urlsplit(url).query)["code_challenge"][0]


@pytest.mark.anyio
async def test_a_state_cannot_be_redeemed_twice() -> None:
    # Otherwise a replayed callback mints a second session from a single consent.
    sign_in = sign_in_for(Recorder())
    _, state = redeem(sign_in)
    await sign_in.complete(code="code-1", state=state)

    with pytest.raises(AuthorizationExpired):
        await sign_in.complete(code="code-1", state=state)


@pytest.mark.anyio
async def test_an_unknown_state_is_refused() -> None:
    sign_in = sign_in_for(Recorder())

    with pytest.raises(AuthorizationExpired):
        await sign_in.complete(code="code-1", state="state-nobody-issued")


@pytest.mark.anyio
async def test_an_expired_authorization_is_refused() -> None:
    sign_in = sign_in_for(Recorder())
    verifier = new_code_verifier()
    sign_in._pending.remember(  # noqa: SLF001 - reaching in beats sleeping ten minutes
        PendingAuthorization(
            state="stale",
            code_verifier=verifier,
            created_at=utc_now() - timedelta(minutes=20),
            expires_at=utc_now() - timedelta(minutes=10),
        )
    )

    with pytest.raises(AuthorizationExpired):
        await sign_in.complete(code="code-1", state="stale")


@pytest.mark.anyio
async def test_a_grant_covering_no_site_is_refused() -> None:
    # Consent can succeed while covering nothing, and every later read would then
    # fail with an unrelated-looking error.
    sign_in = sign_in_for(Recorder(resources=[]))
    _, state = redeem(sign_in)

    with pytest.raises(NoSiteGranted):
        await sign_in.complete(code="code-1", state=state)


SECOND_SITE = {"id": "b0000000-0000-4000-8000-000000000000", "url": "https://other.atlassian.net"}


@pytest.mark.anyio
async def test_a_grant_covering_several_sites_is_refused_rather_than_guessed() -> None:
    # The list order is not part of any contract. Taking the first would make the
    # tenant -- and every permission boundary resting on it -- depend on an ordering
    # that can differ between two sign-ins of the same user.
    sign_in = sign_in_for(
        Recorder(resources=[{"id": CLOUD_ID, "url": SITE_URL}, SECOND_SITE])
    )
    _, state = redeem(sign_in)

    with pytest.raises(AmbiguousSiteGrant):
        await sign_in.complete(code="code-1", state=state)


@pytest.mark.anyio
async def test_a_pinned_site_is_selected_out_of_several() -> None:
    sessions = InMemorySessionStore()
    sign_in = sign_in_for(
        Recorder(resources=[SECOND_SITE, {"id": CLOUD_ID, "url": SITE_URL}]),
        sessions=sessions,
    )
    sign_in._expected_cloud_id = CLOUD_ID  # noqa: SLF001 - the deployment's pin
    _, state = redeem(sign_in)

    token = await sign_in.complete(code="code-1", state=state)

    session = sessions.get_by_token_hash(session_token_hash(token))
    assert session is not None
    # Chosen by name, not by position: the pinned site is second in the payload.
    assert session.tenant_id == CLOUD_ID


@pytest.mark.anyio
async def test_a_pinned_site_that_was_not_granted_is_refused() -> None:
    # The same failure the credentials import script guards with --attendu. Without
    # it the mistake surfaces much later, as a tool refusing for no visible reason.
    sign_in = sign_in_for(Recorder(resources=[SECOND_SITE]))
    sign_in._expected_cloud_id = CLOUD_ID  # noqa: SLF001 - the deployment's pin
    _, state = redeem(sign_in)

    with pytest.raises(UnexpectedSiteGranted):
        await sign_in.complete(code="code-1", state=state)


@pytest.mark.anyio
async def test_a_single_site_still_derives_the_tenant_without_a_pin() -> None:
    # The ordinary case must stay ordinary: one site, no configuration needed.
    sessions = InMemorySessionStore()
    sign_in = sign_in_for(Recorder(), sessions=sessions)
    _, state = redeem(sign_in)

    token = await sign_in.complete(code="code-1", state=state)

    session = sessions.get_by_token_hash(session_token_hash(token))
    assert session is not None
    assert session.tenant_id == CLOUD_ID


@pytest.mark.anyio
async def test_a_refused_exchange_does_not_forward_the_provider_body() -> None:
    sign_in = sign_in_for(Recorder(token_status=401))
    _, state = redeem(sign_in)

    with pytest.raises(ProviderRefused) as raised:
        await sign_in.complete(code="code-1", state=state)

    # The body can echo the code or name the client. Nothing of it reaches a browser.
    assert "invalid_grant" not in str(raised.value)
    assert "invalid_grant" not in raised.value.safe_message


@pytest.mark.anyio
async def test_the_credentials_never_render_themselves() -> None:
    # A model whose repr carries a refresh token puts it in the first traceback that
    # touches it, and from there into a log and a backup.
    from app.auth.adapters.memory import InMemoryDelegatedGrantSink

    grants = InMemoryDelegatedGrantSink()
    sign_in = sign_in_for(Recorder(), grants=grants)
    _, state = redeem(sign_in)
    await sign_in.complete(code="code-1", state=state)

    stored = grants.get(tenant_id=CLOUD_ID, user_id=ACCOUNT)
    assert stored is not None
    assert stored.refresh_token == "rt-secret"
    assert "rt-secret" not in repr(stored)
    assert "at-secret" not in str(stored)


def app_with_sign_in(recorder: Recorder, *, enabled: bool = True):
    settings = Settings(environment="test")
    container = build_container(settings)
    container = replace(
        container,
        settings=settings.model_copy(update={"auth_mode": SESSION_MODE}),
        sign_in=sign_in_for(recorder, sessions=container.sessions) if enabled else None,
    )
    return create_app(settings, container), container


def test_the_route_refuses_when_no_oauth_app_is_registered() -> None:
    app, _ = app_with_sign_in(Recorder(), enabled=False)

    response = TestClient(app).get("/api/auth/atlassian/start", follow_redirects=False)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SIGN_IN_DISABLED"


def test_the_start_route_redirects_to_atlassian() -> None:
    app, _ = app_with_sign_in(Recorder())

    response = TestClient(app).get("/api/auth/atlassian/start", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://auth.atlassian.com/authorize?")


def test_the_callback_sets_a_hardened_cookie_and_signs_the_caller_in() -> None:
    app, container = app_with_sign_in(Recorder())
    # https, because the cookie carries Secure everywhere but plain-HTTP localhost:
    # over http the client would simply refuse to send it back, which is the point.
    client = TestClient(app, base_url="https://testserver")
    start = client.get("/api/auth/atlassian/start", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]

    done = client.get(
        f"/api/auth/atlassian/callback?code=code-1&state={state}",
        follow_redirects=False,
    )

    assert done.status_code == 303
    raw = done.headers["set-cookie"]
    # httponly: an injected script cannot read the session. secure: it never travels
    # in clear. samesite: it is not attached to cross-site posts.
    assert "HttpOnly" in raw
    assert "Secure" in raw
    assert "samesite=lax" in raw.lower()
    # The identity now works without a single identity header.
    created = client.post("/api/conversations", json={"title": "Suivi"})
    assert created.status_code == 201


def test_signing_out_revokes_server_side_and_not_only_in_the_browser() -> None:
    app, container = app_with_sign_in(Recorder())
    # https, because the cookie carries Secure everywhere but plain-HTTP localhost:
    # over http the client would simply refuse to send it back, which is the point.
    client = TestClient(app, base_url="https://testserver")
    start = client.get("/api/auth/atlassian/start", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    client.get(f"/api/auth/atlassian/callback?code=code-1&state={state}", follow_redirects=False)
    token = client.cookies[SESSION_COOKIE_NAME]

    assert client.post("/api/auth/atlassian/signout").status_code == 204

    # A copied token must be dead too, not merely absent from this browser.
    assert container.sessions.get_by_token_hash(session_token_hash(token)) is None


def test_an_enabled_sign_in_without_its_registration_is_refused_at_construction() -> None:
    # Failing at startup beats failing at the callback, where the user is already
    # halfway through a consent screen.
    with pytest.raises(ValueError, match="client id"):
        Settings(environment="test", atlassian_oauth_enabled=True)


def registered(**changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": "development",
        "atlassian_oauth_enabled": True,
        "atlassian_oauth_client_id": "client-abc",
        "atlassian_oauth_client_secret_file": Path("secret"),
        "atlassian_oauth_redirect_uri": "https://app.example/callback",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def test_the_development_callback_over_plain_http_is_accepted_on_loopback() -> None:
    # The one exception, and it is what the PFE actually runs.
    settings = registered(
        atlassian_oauth_redirect_uri="http://localhost:8000/api/auth/atlassian/callback"
    )

    assert settings.atlassian_oauth_redirect_uri.endswith("/api/auth/atlassian/callback")


@pytest.mark.parametrize(
    "redirect",
    [
        "http://app.example/callback",
        # Starts with "http://localhost" and is not local at all: prefix matching
        # would have let this through, and the code would have gone to its owner.
        "http://localhost.evil.test/callback",
        "http://192.168.1.10:8000/callback",
    ],
)
def test_a_plain_http_callback_is_refused_off_the_loopback_host(redirect: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        registered(atlassian_oauth_redirect_uri=redirect)


@pytest.mark.parametrize("environment", ["test", "production"])
def test_a_plain_http_callback_is_refused_outside_development(environment: str) -> None:
    # Loopback alone is not enough. Both sides of the fence have to hold.
    with pytest.raises(ValueError, match="development environment"):
        registered(
            environment=environment,
            repository_backend="postgres" if environment == "production" else "memory",
            auth_mode="session",
            atlassian_oauth_redirect_uri="http://localhost:8000/callback",
        )


def test_the_post_sign_in_target_must_be_a_path() -> None:
    # A full URL there is an open redirect, the classic hole in this flow.
    with pytest.raises(ValueError, match="path"):
        registered(atlassian_oauth_post_login_path="https://elsewhere.example/")


@pytest.mark.parametrize("target", ["//elsewhere.example", "/\\elsewhere.example"])
def test_a_protocol_relative_post_sign_in_target_is_refused(target: str) -> None:
    # It starts with a slash, so a leading-slash check passes it -- and the browser
    # leaves the site anyway. Backslash because some browsers fold it to a slash.
    with pytest.raises(ValueError, match="protocol-relative"):
        registered(atlassian_oauth_post_login_path=target)


def test_the_callback_body_never_carries_a_token() -> None:
    app, _ = app_with_sign_in(Recorder())
    client = TestClient(app)
    start = client.get("/api/auth/atlassian/start", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]

    done = client.get(
        f"/api/auth/atlassian/callback?code=code-1&state={state}",
        follow_redirects=False,
    )

    assert "at-secret" not in done.text
    assert "rt-secret" not in done.text
    assert "rt-secret" not in json.dumps(dict(done.headers))
