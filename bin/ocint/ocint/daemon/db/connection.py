from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry


class SqliteConnection(Protocol):
    def execute(self, statement: str) -> None: ...


def create_daemon_engine(path: Path, busy_timeout_ms: int = 5000) -> Engine:
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(path)), future=True)

    @event.listens_for(engine, "connect")
    def apply_pragmas(connection: SqliteConnection, _record: ConnectionPoolEntry) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        if path.exists():
            path.chmod(0o600)

    return engine


def alembic_config(path: Path | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("file_template", "%%(year)d%%(month).2d%%(day).2d_%%(slug)s")
    if path is not None:
        config.set_main_option("sqlalchemy.url", str(URL.create("sqlite+pysqlite", database=str(path))))
    return config


def migrate_daemon_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(path), "head")
    path.chmod(0o600)


def downgrade_daemon_db(path: Path) -> None:
    command.downgrade(alembic_config(path), "base")


def current_daemon_head_revision() -> str:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    if len(heads) != 1:
        raise ValueError(f"daemon migrations must have exactly one head; found {len(heads)}")
    return heads[0]


@contextmanager
def daemon_connection(path: Path) -> Iterator[Connection]:
    engine = create_daemon_engine(path)
    with engine.connect() as connection:
        yield connection
    engine.dispose()
