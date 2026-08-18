from threading import RLock

from app.sessions.domain import Session


class InMemorySessionStore:
    """Development-only, process-local session store."""

    def __init__(self) -> None:
        self._items: dict[str, Session] = {}
        self._lock = RLock()

    def create(self, session: Session) -> None:
        with self._lock:
            self._items[session.token_hash] = session

    def get_by_token_hash(self, token_hash: str) -> Session | None:
        with self._lock:
            return self._items.get(token_hash)

    def revoke(self, token_hash: str) -> None:
        with self._lock:
            self._items.pop(token_hash, None)
