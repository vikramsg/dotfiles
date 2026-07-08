from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session

from ocint.ctx.config import CtxBackendConfig

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
DUCKDB_MIGRATIONS_DIR = Path(__file__).parent / "duckdb_migrations"


def create_ctx_engine(config: CtxBackendConfig) -> Engine:
    url = _sqlalchemy_url(config)
    engine = create_engine(url, future=True)
    if config.backend == "duckdb":
        extension_dir = config.db_path.parent / "duckdb_extensions"
        extension_dir.mkdir(parents=True, exist_ok=True)

        @event.listens_for(engine, "connect")
        def _set_duckdb_extension_dir(dbapi_connection: Any, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f"SET extension_directory='{_sql_string(extension_dir)}'")
            finally:
                cursor.close()

        return engine
    if config.backend != "sqlite":
        return engine

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


def migrate_ctx_db(config: CtxBackendConfig) -> None:
    """Run Alembic against the ocint ctx DB only, creating its parent as needed."""
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(_migrations_dir(config)))
    alembic_config.set_main_option("sqlalchemy.url", str(_sqlalchemy_url(config)))
    command.upgrade(alembic_config, "head")


@contextmanager
def ctx_session(config: CtxBackendConfig, *, commit: bool) -> Iterator[Session]:
    engine = create_ctx_engine(config)
    session = Session(engine, future=True)
    try:
        yield session
        if commit:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def _sqlalchemy_url(config: CtxBackendConfig) -> URL:
    if config.backend == "sqlite":
        return URL.create("sqlite+pysqlite", database=str(config.db_path))
    return URL.create("duckdb", database=str(config.db_path))


def _migrations_dir(config: CtxBackendConfig) -> Path:
    return MIGRATIONS_DIR if config.backend == "sqlite" else DUCKDB_MIGRATIONS_DIR


def _sql_string(value: Path) -> str:
    return str(value).replace("'", "''")
