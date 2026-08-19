from typing import Protocol

from app.auth.domain import DelegatedCredentials, PendingAuthorization


class PendingAuthorizationStore(Protocol):
    """In-flight sign-ins, addressed by their state value."""

    def remember(self, pending: PendingAuthorization) -> None: ...

    def take(self, state: str) -> PendingAuthorization | None:
        """Return the pending authorization and remove it.

        Single use by construction: a state that could be redeemed twice would let a
        replayed callback mint a second session.
        """
        ...


class DelegatedGrantSink(Protocol):
    """Where consent deposits the credentials it produced.

    A port rather than a direct write: the durable implementation encrypts at rest
    and is a separate slice, and until then nothing has to pretend to persist.
    """

    def store(self, credentials: DelegatedCredentials) -> None: ...
