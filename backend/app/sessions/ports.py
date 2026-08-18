from typing import Protocol

from app.sessions.domain import Session


class SessionStore(Protocol):
    """Server-held sessions, addressed by the hash of the presented token."""

    def create(self, session: Session) -> None: ...

    def get_by_token_hash(self, token_hash: str) -> Session | None: ...

    def revoke(self, token_hash: str) -> None: ...
