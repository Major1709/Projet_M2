from threading import RLock

from app.auth.domain import DelegatedCredentials, PendingAuthorization


class InMemoryPendingAuthorizationStore:
    """Process-local in-flight sign-ins.

    Adequate for a single process: a pending authorization lives for minutes, and
    losing it on restart costs one retry rather than a session.
    """

    def __init__(self) -> None:
        self._items: dict[str, PendingAuthorization] = {}
        self._lock = RLock()

    def remember(self, pending: PendingAuthorization) -> None:
        with self._lock:
            self._items[pending.state] = pending

    def take(self, state: str) -> PendingAuthorization | None:
        with self._lock:
            return self._items.pop(state, None)


class InMemoryDelegatedGrantSink:
    """Holds delegated credentials in process memory, and never on disk.

    Stands in until the encrypted store exists. Honest for a developer machine, and
    fail-safe by omission: a restart loses the grant, which forces consent again
    rather than leaving a refresh token lying in a file nobody rotates.
    """

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], DelegatedCredentials] = {}
        self._lock = RLock()

    def store(self, credentials: DelegatedCredentials) -> None:
        with self._lock:
            self._items[(credentials.tenant_id, credentials.user_id)] = credentials

    def get(self, *, tenant_id: str, user_id: str) -> DelegatedCredentials | None:
        with self._lock:
            return self._items.get((tenant_id, user_id))
