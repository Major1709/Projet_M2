import logging
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
def expected_schema_revisions() -> frozenset[str]:
    """Les revisions de tete que le code de cette image attend.

    Lues dans le repertoire de migrations plutot que figees dans une constante : une
    valeur ecrite a la main serait juste le jour ou on l'ecrit et fausse a la
    migration suivante, ce qui est la facon la plus sure de rendre ce controle
    inutile.

    Mise en cache : le repertoire ne change pas pendant la vie du processus, et la
    sonde est interrogee toutes les quinze secondes.
    """

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


def database_is_ready(engine: Engine) -> bool:
    """Joignable ET au bon schema.

    Le second controle manquait, et son absence n'etait pas theorique : la base de
    developpement a tourne deux migrations en retard pendant des semaines sans que
    rien ne le signale. Les lectures fonctionnaient -- elles ne touchaient pas les
    colonnes ajoutees -- et le service se declarait pret. Le decalage n'est apparu
    qu'a la premiere ecriture, sous la forme d'un "column does not exist" que rien
    dans la sonde n'avait laisse prevoir.

    Une sonde qui ne verifie que la connexion repond a "puis-je parler a la base",
    alors que la question posee est "puis-je servir du trafic".

    Echoue en cas de doute, y compris quand la tete attendue est indeterminable :
    un deploiement qui ne sait pas quel schema il attend ne sait pas non plus s'il
    peut servir, et un refus bruyant se diagnostique en une minute la ou un
    silence coute une panne d'ecriture.
    """

    try:
        expected = expected_schema_revisions()
    except Exception:
        logger.exception("The expected schema revision could not be determined")
        return False

    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT 1")).scalar_one() != 1:
                return False
            applied = {
                row[0]
                for row in connection.execute(text("SELECT version_num FROM alembic_version"))
            }
    except SQLAlchemyError:
        # Inclut la table alembic_version absente, ce qui est le cas d'une base sur
        # laquelle aucune migration n'a jamais tourne : pas prete, et pour de bon.
        logger.warning("The database is unreachable or carries no migration history")
        return False

    if applied != expected:
        # Les deux ensembles sont journalises : savoir seulement "ce n'est pas la
        # bonne version" oblige a aller les chercher a la main, au pire moment.
        logger.error(
            "The database schema is not the one this build expects",
            extra={"schema_applied": sorted(applied), "schema_expected": sorted(expected)},
        )
        return False
    return True
