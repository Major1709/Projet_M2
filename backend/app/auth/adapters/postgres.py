import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from app.auth.crypto import CURRENT_KEY_VERSION, GrantCipher, GrantCipherError
from app.auth.domain import DelegatedCredentials
from app.persistence.schema import delegated_grants

logger = logging.getLogger(__name__)

# Renew this long before the token actually lapses. A grant that expires while a
# read is in flight fails the read, and the clocks of two machines are never
# exactly equal, so the margin absorbs both.
RENEWAL_MARGIN_SECONDS = 120


def _advisory_key(tenant_id: str, user_id: str) -> str:
    return f"delegated-grant:{tenant_id}\x1f{user_id}"


class PostgresDelegatedGrantStore:
    """Delegated Atlassian grants, encrypted at rest and renewed under a lock.

    The lock is the part that is easy to leave out and expensive to omit.
    Atlassian rotates the refresh token on every exchange: the old one dies the
    moment a new one is issued. If two workers renew the same grant at once, both
    obtain a fresh token, and whichever writes second overwrites a token the
    provider has already invalidated. The stored grant is then dead, and the only
    remedy is to send the person through consent again -- for a race nobody
    observed.

    So renewal takes a PostgreSQL advisory lock on the grant's identity, and
    re-reads inside it. The second caller then finds the work already done and
    uses the result instead of repeating it.
    """

    def __init__(
        self,
        session_factory: sessionmaker[DatabaseSession],
        cipher: GrantCipher,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    def store(self, credentials: DelegatedCredentials) -> None:
        moment = datetime.now(UTC)
        expires_at = datetime.fromtimestamp(credentials.expires_at, UTC)
        statement = insert(delegated_grants).values(
            tenant_id=credentials.tenant_id,
            user_id=credentials.user_id,
            access_token=self._cipher.encrypt(
                credentials.access_token,
                tenant_id=credentials.tenant_id,
                user_id=credentials.user_id,
            ),
            refresh_token=self._cipher.encrypt(
                credentials.refresh_token,
                tenant_id=credentials.tenant_id,
                user_id=credentials.user_id,
            ),
            key_version=CURRENT_KEY_VERSION,
            expires_at=expires_at,
            updated_at=moment,
        )
        # Signing in again replaces the grant rather than adding one. Two rows for
        # one person would leave the reads choosing between an old token and a new
        # one with nothing to decide on.
        statement = statement.on_conflict_do_update(
            index_elements=["tenant_id", "user_id"],
            set_={
                "access_token": statement.excluded.access_token,
                "refresh_token": statement.excluded.refresh_token,
                "key_version": statement.excluded.key_version,
                "expires_at": statement.excluded.expires_at,
                "updated_at": statement.excluded.updated_at,
            },
        )
        with self._session_factory.begin() as database:
            database.execute(statement)

    def get(self, *, tenant_id: str, user_id: str) -> DelegatedCredentials | None:
        with self._session_factory() as database:
            row = self._read(database, tenant_id=tenant_id, user_id=user_id)
        return row

    def revoke(self, *, tenant_id: str, user_id: str) -> None:
        with self._session_factory.begin() as database:
            database.execute(
                delete(delegated_grants).where(
                    delegated_grants.c.tenant_id == tenant_id,
                    delegated_grants.c.user_id == user_id,
                )
            )

    async def valid_credentials(
        self,
        *,
        tenant_id: str,
        user_id: str,
        renew: Callable[[DelegatedCredentials], Awaitable[DelegatedCredentials]],
    ) -> DelegatedCredentials | None:
        """The grant, renewed first if it is close to lapsing.

        ``renew`` performs the provider exchange and is injected rather than
        imported: this class knows how to serialise a renewal and how to store the
        result, and nothing about Atlassian.
        """

        current = self.get(tenant_id=tenant_id, user_id=user_id)
        if current is None:
            return None
        if not self._needs_renewal(current):
            return current

        with self._session_factory.begin() as database:
            # Blocks until whoever else is renewing this exact grant is done, and
            # is released when the transaction ends -- including on a crash, which
            # a lock table would not guarantee.
            database.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": _advisory_key(tenant_id, user_id)},
            )
            # Re-read inside the lock. The other caller may have finished while we
            # waited, and renewing again would burn the refresh token they just
            # obtained.
            fresh = self._read(database, tenant_id=tenant_id, user_id=user_id)
            if fresh is None:
                return None
            if not self._needs_renewal(fresh):
                return fresh
            renewed = await renew(fresh)
            self._write(database, renewed)
            return renewed

    @staticmethod
    def _needs_renewal(credentials: DelegatedCredentials) -> bool:
        remaining = credentials.expires_at - datetime.now(UTC).timestamp()
        return remaining <= RENEWAL_MARGIN_SECONDS

    def _read(
        self,
        database: DatabaseSession,
        *,
        tenant_id: str,
        user_id: str,
    ) -> DelegatedCredentials | None:
        row = (
            database.execute(
                select(delegated_grants).where(
                    delegated_grants.c.tenant_id == tenant_id,
                    delegated_grants.c.user_id == user_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        try:
            return DelegatedCredentials(
                tenant_id=row["tenant_id"],
                user_id=row["user_id"],
                access_token=self._cipher.decrypt(
                    row["access_token"], tenant_id=tenant_id, user_id=user_id
                ),
                refresh_token=self._cipher.decrypt(
                    row["refresh_token"], tenant_id=tenant_id, user_id=user_id
                ),
                expires_at=row["expires_at"].timestamp(),
            )
        except GrantCipherError:
            # A row sealed with a key this deployment no longer holds, or one that
            # was tampered with. Treated as absent rather than fatal: the person
            # signs in again, which is recoverable, where a raised error on every
            # read would not be. Logged without the row's contents.
            logger.warning(
                "a stored delegated grant could not be decrypted",
                extra={"tenant_id": tenant_id, "key_version": row["key_version"]},
            )
            return None

    def _write(self, database: DatabaseSession, credentials: DelegatedCredentials) -> None:
        database.execute(
            delegated_grants.update()
            .where(
                delegated_grants.c.tenant_id == credentials.tenant_id,
                delegated_grants.c.user_id == credentials.user_id,
            )
            .values(
                access_token=self._cipher.encrypt(
                    credentials.access_token,
                    tenant_id=credentials.tenant_id,
                    user_id=credentials.user_id,
                ),
                refresh_token=self._cipher.encrypt(
                    credentials.refresh_token,
                    tenant_id=credentials.tenant_id,
                    user_id=credentials.user_id,
                ),
                key_version=CURRENT_KEY_VERSION,
                expires_at=datetime.fromtimestamp(credentials.expires_at, UTC),
                updated_at=func.now(),
            )
        )
