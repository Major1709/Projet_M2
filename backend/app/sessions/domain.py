import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# 32 bytes of urandom, url-safe. The value is the credential: it is handed to the
# browser once and never stored anywhere in that form.
SESSION_TOKEN_BYTES = 32
SESSION_COOKIE_NAME = "pka_session"
DEFAULT_SESSION_LIFETIME = timedelta(hours=12)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def session_token_hash(token: str) -> str:
    """What the store holds instead of the token itself.

    A leaked database must not yield usable sessions. Plain SHA-256 rather than a
    password hash on purpose: the token is 256 bits of urandom, so there is no
    guessable input to slow down, and a per-request password hash would only add
    latency to every authenticated call.
    """

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Session(BaseModel):
    """One signed-in identity, held by the server and named by an opaque token."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    token_hash: str = Field(min_length=64, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)
    # Absolute, not sliding. A session that renews itself on every request never
    # ends for an attacker who holds the token, which is the case the expiry exists
    # for.
    expires_at: datetime

    def is_active(self, *, at: datetime | None = None) -> bool:
        return (at or utc_now()) < self.expires_at
