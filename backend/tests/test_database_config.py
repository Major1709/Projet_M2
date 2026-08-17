import hashlib
import hmac
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core import database
from app.core.config import Settings
from app.core.database import build_database_url


def postgres_settings(password_file: Path) -> Settings:
    return Settings(
        environment="test",
        repository_backend="postgres",
        database_host="postgres.internal",
        database_port=5432,
        database_name="pka_test",
        database_user="pka_test_user",
        database_password_file=password_file,
    )


def test_postgres_requires_all_split_database_settings() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL repository configuration"):
        Settings(
            environment="test",
            repository_backend="postgres",
            database_host=None,
            database_port=None,
            database_name=None,
            database_user=None,
            database_password_file=None,
        )


def test_database_url_field_is_not_supported() -> None:
    assert "database_url" not in Settings.model_fields
    with pytest.raises(ValidationError, match="PKA_DATABASE_PASSWORD_FILE"):
        Settings(
            environment="test",
            repository_backend="postgres",
            database_host="postgres.internal",
            database_port=5432,
            database_name="pka_test",
            database_user="pka_test_user",
            database_password_file=None,
        )


def test_database_url_reads_password_only_from_file(tmp_path: Path) -> None:
    password_file = tmp_path / "postgres_password"
    expected_password = "synthetic-password-with-specials:/@"
    password_file.write_text(expected_password + "\n", encoding="utf-8")

    url = build_database_url(postgres_settings(password_file))

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "postgres.internal"
    assert url.port == 5432
    assert url.database == "pka_test"
    assert url.username == "pka_test_user"
    assert url.password is not None
    assert hmac.compare_digest(
        hashlib.sha256(url.password.encode()).digest(),
        hashlib.sha256(expected_password.encode()).digest(),
    )
    assert "***" in url.render_as_string(hide_password=True)


def test_database_password_file_error_is_safe(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing-password"

    with pytest.raises(
        ValueError,
        match="Unable to read the configured database password file",
    ) as error:
        build_database_url(postgres_settings(missing_file))

    assert str(missing_file) not in str(error.value)


def test_database_engine_has_bounded_connection_and_pool_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password_file = tmp_path / "postgres_password"
    password_file.write_text("synthetic-engine-password\n", encoding="utf-8")
    captured_kwargs: dict[str, object] = {}

    def capture_create_engine(*_: object, **kwargs: object) -> object:
        captured_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(database, "create_engine", capture_create_engine)
    settings = postgres_settings(password_file)

    database.create_database_engine(settings)

    assert captured_kwargs["echo"] is False
    assert captured_kwargs["hide_parameters"] is True
    assert captured_kwargs["pool_pre_ping"] is True
    assert captured_kwargs["pool_timeout"] == 2
    assert captured_kwargs["connect_args"] == {
        "connect_timeout": 2,
        "options": "-c statement_timeout=2000",
    }


def test_memory_repository_does_not_build_a_database_url() -> None:
    with pytest.raises(ValueError, match="postgres repository"):
        build_database_url(Settings(environment="test", repository_backend="memory"))
