"""La sonde de disponibilite repond a "puis-je servir du trafic", pas a "puis-je
parler a la base".

Le defaut que ces tests ferment n'etait pas theorique : la base de developpement a
tourne deux migrations en retard pendant des semaines. Les lectures fonctionnaient --
elles ne touchaient pas les colonnes ajoutees -- et le service se declarait pret. Le
decalage n'est apparu qu'a la premiere ecriture, sous la forme d'un "column does not
exist" que rien dans la sonde n'avait laisse prevoir.
"""

import logging

import pytest
from sqlalchemy.exc import OperationalError

from app.core.database import database_is_ready, expected_schema_revisions


def test_the_expected_head_is_read_from_the_migrations_themselves() -> None:
    """Figee dans une constante, elle serait juste le jour ou on l'ecrit et fausse a
    la migration suivante -- la facon la plus sure de rendre ce controle inutile."""

    heads = expected_schema_revisions()

    assert len(heads) == 1, "plusieurs tetes de migration : la branche doit etre fusionnee"
    assert next(iter(heads)).startswith("2026")


def test_an_unreachable_database_is_not_ready() -> None:
    class DeadEngine:
        def connect(self):
            raise OperationalError("connexion refusee", None, None)

    assert database_is_ready(DeadEngine()) is False


class FakeConnection:
    def __init__(self, *, applied: set[str] | None, alive: bool = True) -> None:
        self._applied = applied
        self._alive = alive

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        rendu = str(statement)
        if "SELECT 1" in rendu:
            return _Scalar(1 if self._alive else 0)
        if self._applied is None:
            raise OperationalError("relation alembic_version inexistante", None, None)
        return [(revision,) for revision in self._applied]


class _Scalar:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connect(self):
        return self._connection


def test_a_schema_at_head_is_ready() -> None:
    engine = FakeEngine(FakeConnection(applied=set(expected_schema_revisions())))

    assert database_is_ready(engine) is True


def test_a_stale_schema_is_not_ready(caplog: pytest.LogCaptureFixture) -> None:
    """Le coeur du correctif. Deux migrations en retard, connexion parfaitement
    saine : c'etait exactement l'etat qui se declarait pret."""

    engine = FakeEngine(FakeConnection(applied={"20260820_0005"}))

    with caplog.at_level(logging.ERROR):
        assert database_is_ready(engine) is False

    record = next(
        r for r in caplog.records if "not the one this build expects" in r.getMessage()
    )
    # Les deux ensembles sont journalises : savoir seulement "mauvaise version"
    # obligerait a aller les chercher a la main, au pire moment.
    assert record.schema_applied == ["20260820_0005"]
    assert record.schema_expected == sorted(expected_schema_revisions())


def test_a_schema_ahead_of_this_build_is_not_ready() -> None:
    """L'autre sens compte aussi : une image ancienne devant une base deja migree ne
    connait pas les colonnes qu'elle va rencontrer."""

    engine = FakeEngine(FakeConnection(applied={"20270101_9999"}))

    assert database_is_ready(engine) is False


def test_a_database_without_migration_history_is_not_ready() -> None:
    """Aucune migration n'a jamais tourne : pas prete, et pour de bon."""

    engine = FakeEngine(FakeConnection(applied=None))

    assert database_is_ready(engine) is False
