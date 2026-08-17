from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def _read_password_file(path: Path) -> str:
    try:
        password = path.read_text(encoding="utf-8").rstrip("\r\n")
    except OSError:
        raise ValueError("Unable to read the configured database password file") from None
    if not password:
        raise ValueError("The configured database password file is empty")
    return password


def build_database_url(settings: Settings) -> URL:
    """Build a psycopg URL without interpolating credentials into a string."""

    if settings.repository_backend != "postgres":
        raise ValueError("A database URL can only be built for the postgres repository")

    if (
        settings.database_host is None
        or settings.database_port is None
        or settings.database_name is None
        or settings.database_user is None
        or settings.database_password_file is None
    ):
        raise ValueError("PostgreSQL repository configuration is incomplete")

    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.database_user,
        password=_read_password_file(settings.database_password_file),
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
    )


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        build_database_url(settings),
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        connect_args={
            "connect_timeout": settings.database_connect_timeout_seconds,
            "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def database_is_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1
    except SQLAlchemyError:
        return False
