import logging
from datetime import timedelta

from app.auth.client import AtlassianOAuthClient, authorization_url
from app.auth.domain import (
    AUTHORIZATION_LIFETIME,
    DelegatedCredentials,
    PendingAuthorization,
    new_code_verifier,
    new_state,
    utc_now,
)
from app.auth.errors import AuthorizationExpired
from app.auth.ports import DelegatedGrantSink, PendingAuthorizationStore
from app.sessions.domain import (
    Session,
    new_session_token,
    session_token_hash,
)
from app.sessions.ports import SessionStore

logger = logging.getLogger(__name__)


class AtlassianSignIn:
    """Turns Atlassian consent into a server-held session.

    The tenant is the cloud id of the site the user chose on the consent screen, and
    the user is their Atlassian account id. Both are read back from the provider
    rather than accepted from the request: that is the whole difference with the
    header mode this replaces.
    """

    def __init__(
        self,
        *,
        client: AtlassianOAuthClient,
        pending: PendingAuthorizationStore,
        sessions: SessionStore,
        grants: DelegatedGrantSink,
        client_id: str,
        redirect_uri: str,
        session_lifetime: timedelta,
        expected_cloud_id: str | None = None,
    ) -> None:
        self._client = client
        self._pending = pending
        self._sessions = sessions
        self._grants = grants
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._session_lifetime = session_lifetime
        self._expected_cloud_id = expected_cloud_id

    def begin(self) -> str:
        """Remember the verifier, then hand back the URL to send the browser to."""

        state = new_state()
        verifier = new_code_verifier()
        self._pending.remember(
            PendingAuthorization(
                state=state,
                code_verifier=verifier,
                expires_at=utc_now() + AUTHORIZATION_LIFETIME,
            )
        )
        return authorization_url(
            client_id=self._client_id,
            redirect_uri=self._redirect_uri,
            state=state,
            verifier=verifier,
        )

    async def complete(self, *, code: str, state: str) -> str:
        """Redeem the code and return the session token to set as a cookie."""

        pending = self._pending.take(state)
        # Taken, not read: a state that survived redemption would let a replayed
        # callback mint a second session from one consent.
        if pending is None or not pending.is_active():
            raise AuthorizationExpired()

        document = await self._client.exchange_code(
            code=code,
            verifier=pending.code_verifier,
        )
        access_token = str(document["access_token"])
        site = await self._client.granted_site(
            access_token,
            expected_cloud_id=self._expected_cloud_id,
        )
        account_id = await self._client.account_id(access_token)

        expires_in = document.get("expires_in")
        self._grants.store(
            DelegatedCredentials(
                tenant_id=site.cloud_id,
                user_id=account_id,
                access_token=access_token,
                refresh_token=str(document["refresh_token"]),
                # An absent lifetime counts as expired: the next call renews rather
                # than presenting a token whose age nobody knows.
                expires_at=utc_now().timestamp() + float(expires_in)
                if isinstance(expires_in, int | float)
                else 0.0,
            )
        )

        token = new_session_token()
        self._sessions.create(
            Session(
                token_hash=session_token_hash(token),
                tenant_id=site.cloud_id,
                user_id=account_id,
                expires_at=utc_now() + self._session_lifetime,
            )
        )
        # The site url identifies which Atlassian instance was granted, and it is not
        # a secret. The tokens are never logged, here or anywhere.
        logger.info("atlassian sign-in completed", extra={"site_url": site.url})
        return token
