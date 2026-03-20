from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app


TRUNCATE_TABLES = (
    "pull_request_analyses",
    "pull_requests",
    "flaky_test_runs",
)


def _assert_safe_test_database_url(test_database_url: str, app_database_url: str) -> str:
    test_url = make_url(test_database_url)
    app_url = make_url(app_database_url)

    if test_url.database == app_url.database:
        raise RuntimeError("TEST_DATABASE_URL must point to a different database than DATABASE_URL")

    database_name = (test_url.database or "").strip()
    if not database_name:
        raise RuntimeError("TEST_DATABASE_URL must include an explicit database name")
    if not database_name.endswith("_test"):
        raise RuntimeError(
            "Refusing to reset a database that does not end with '_test'. "
            "Rename the test database to something like devaccel_test."
        )

    host = (test_url.host or "").strip().lower()
    if host and host not in {"localhost", "127.0.0.1", "postgres"}:
        raise RuntimeError(
            "Refusing to reset a non-local test database host. "
            "Use localhost/127.0.0.1/postgres for destructive test database resets."
        )

    return database_name


def _reset_public_schema(engine: Engine, expected_database_name: str) -> None:
    with engine.begin() as connection:
        current_database = connection.execute(text("SELECT current_database()")).scalar_one()
        if current_database != expected_database_name:
            raise RuntimeError(
                f"Refusing to reset schema for unexpected database '{current_database}'. "
                f"Expected '{expected_database_name}'."
            )
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def _truncate_all_tables(engine: Engine) -> None:
    table_list = ", ".join(TRUNCATE_TABLES)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def test_database_url() -> str:
    settings = get_settings()
    url = settings.test_database_url.strip()
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is required for tests. "
            "Add it to .env or export it in the shell before running pytest."
        )
    if url.startswith("sqlite"):
        raise RuntimeError("SQLite is no longer supported for database-backed tests")
    _assert_safe_test_database_url(url, settings.database_url.strip())
    return url


@pytest.fixture(scope="session")
def test_engine(test_database_url: str) -> Generator[Engine, None, None]:
    settings = get_settings()
    expected_database_name = _assert_safe_test_database_url(
        test_database_url,
        settings.database_url.strip(),
    )
    bootstrap_engine = create_engine(test_database_url, future=True)
    _reset_public_schema(bootstrap_engine, expected_database_name)
    bootstrap_engine.dispose()

    root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(root / "alembic"))
    alembic_config.attributes["override_sqlalchemy_url"] = test_database_url
    command.upgrade(alembic_config, "head")

    engine = create_engine(test_database_url, future=True)
    _truncate_all_tables(engine)
    try:
        yield engine
    finally:
        _reset_public_schema(engine, expected_database_name)
        engine.dispose()


@pytest.fixture()
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    _truncate_all_tables(test_engine)
    testing_session_local = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
        class_=Session,
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        _truncate_all_tables(test_engine)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
