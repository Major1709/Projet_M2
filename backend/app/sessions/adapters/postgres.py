from pydantic import ValidationError
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from app.persistence.errors import PersistenceMappingError
from app.persistence.schema import sessions
from app.sessions.domain import Session


class PostgresSessionStore:
    """Sessions in the database the request path already depends on.

    PostgreSQL rather than the Redis the compose already runs: a session lookup sits
    on every authenticated request, and adding a second store there would add a
    client library, a credential and a failure mode to a code path whose whole
    discipline is a narrow outbound surface. Sessions are few, short-lived, and
    swept by expiry.
    """

    def __init__(self, session_factory: sessionmaker[DatabaseSession]) -> None:
        self._session_factory = session_factory

    def create(self, session: Session) -> None:
        with self._session_factory.begin() as database:
            database.execute(
                insert(sessions).values(
                    id=session.id,
                    token_hash=session.token_hash,
                    tenant_id=session.tenant_id,
                    user_id=session.user_id,
                    created_at=session.created_at,
                    expires_at=session.expires_at,
                )
            )

    def get_by_token_hash(self, token_hash: str) -> Session | None:
        statement = select(sessions).where(sessions.c.token_hash == token_hash)
        with self._session_factory() as database:
            row = database.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        try:
            return Session.model_validate(dict(row))
        except ValidationError:
            raise PersistenceMappingError("Stored session is invalid") from None

    def revoke(self, token_hash: str) -> None:
        with self._session_factory.begin() as database:
            database.execute(delete(sessions).where(sessions.c.token_hash == token_hash))
