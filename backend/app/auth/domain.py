import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# Atlassian's own endpoints, fixed here rather than configurable. A configurable
# authorization host is a lever an edited environment file can pull, and it would
# carry an authorization code -- and then a refresh token -- wherever it pointed.
ATLASSIAN_AUTHORIZE_ENDPOINT: Final = "https://auth.atlassian.com/authorize"
ATLASSIAN_OAUTH_TOKEN_ENDPOINT: Final = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_ACCESSIBLE_RESOURCES: Final = (
    "https://api.atlassian.com/oauth/token/accessible-resources"
)
ATLASSIAN_ME_ENDPOINT: Final = "https://api.atlassian.com/me"

# The classic scopes, which Atlassian recommends where they exist, kept to the
# minimum this build reads. No write scope: mutations are refused at construction,
# and a granted scope is a scope a stolen token can use.
#
# Scopes are not the grant type, and the two are easy to conflate. Adding the Jira
# and Confluence APIs in the developer console selects *permissions*; restricting a
# grant to one site is a separate choice made at authorisation time, and this build
# also enforces it server-side through ``atlassian_expected_cloud_id``.
#
# offline_access is what makes the grant renewable. Without it the deployment holds
# an access token for about an hour and then has to send the user back through
# consent, which is not a product.
ATLASSIAN_SCOPES: Final = (
    "offline_access "
    "read:jira-work read:jira-user "
    "read:confluence-content.all read:confluence-space.summary"
)

STATE_BYTES: Final = 32
VERIFIER_BYTES: Final = 64
AUTHORIZATION_LIFETIME: Final = timedelta(minutes=10)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_state() -> str:
    return secrets.token_urlsafe(STATE_BYTES)


def new_code_verifier() -> str:
    return secrets.token_urlsafe(VERIFIER_BYTES)


def code_challenge_for(verifier: str) -> str:
    """S256 challenge for a verifier.

    **Sent, not relied upon.** Atlassian's 3LO documentation describes an
    authorization code flow secured by a ``client_secret``; it does not document
    ``code_challenge`` or ``code_verifier``, and this deployment has not observed
    whether the provider records the challenge and rejects a mismatched verifier.
    Until an exchange with a deliberately wrong verifier is seen to fail, these
    parameters must be treated as inert.

    They are still sent: they cost nothing, and they take effect on their own if the
    provider does honour them. What actually protects this flow today is the
    unguessable single-use ``state``, the server-held ``client_secret``, the code
    being redeemable once, and a cookie the browser will not hand to script.
    """

    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class PendingAuthorization(BaseModel):
    """One in-flight sign-in, held server-side between the two legs of the flow."""

    model_config = ConfigDict(frozen=True)

    state: str = Field(min_length=1, max_length=200)
    code_verifier: str = Field(min_length=43, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime

    def is_active(self, *, at: datetime | None = None) -> bool:
        return (at or utc_now()) < self.expires_at


class DelegatedCredentials(BaseModel):
    """What consent produced, on its way to a store that will encrypt it.

    Deliberately not printable: the string representation of this model would
    otherwise end up in a traceback, and a refresh token in a log is a refresh token
    in a backup.
    """

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    user_id: str
    access_token: str
    refresh_token: str
    expires_at: float

    def __repr__(self) -> str:  # pragma: no cover - trivial, but load bearing
        return f"DelegatedCredentials(tenant_id={self.tenant_id!r}, user_id={self.user_id!r})"

    __str__ = __repr__


class AtlassianSite(BaseModel):
    """One site the granted token covers."""

    model_config = ConfigDict(frozen=True)

    cloud_id: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=500)
