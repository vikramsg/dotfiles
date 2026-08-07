import errno
import fcntl
import os
import stat
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


def create_daemon_engine(path: Path, busy_timeout_ms: int = 2_000) -> Engine:
    if busy_timeout_ms <= 0:
        raise ValueError("database busy timeout must be positive")
    path = _configured_database_path(path)
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(path)), future=True)

    @event.listens_for(engine, "connect")
    def apply_pragmas(connection: SqliteConnection, _record: ConnectionPoolEntry) -> None:
        connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
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
    expanded_path = _configured_database_path(path)
    expanded_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path = expanded_path.resolve()
    with _migration_lock(canonical_path):
        command.upgrade(alembic_config(canonical_path), "head")
        canonical_path.chmod(0o600)


def downgrade_daemon_db(path: Path) -> None:
    canonical_path = _configured_database_path(path).resolve()
    with _migration_lock(canonical_path):
        command.downgrade(alembic_config(canonical_path), "base")


def _configured_database_path(path: Path) -> Path:
    expanded_path = path.expanduser()
    if expanded_path.is_symlink():
        raise PermissionError(f"database file must not be a symbolic link: {expanded_path}")
    return expanded_path


@contextmanager
def _migration_lock(database_path: Path) -> Iterator[None]:
    lock_path = Path(f"{database_path}.migrate.lock")
    try:
        descriptor = os.open(
            lock_path,
            os.O_CLOEXEC | os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR,
            0o600,
        )
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise PermissionError(f"migration lock must not be a symbolic link: {lock_path}") from error
        raise
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise PermissionError(f"migration lock must be a user-owned regular mode-0600 file: {lock_path}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


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
