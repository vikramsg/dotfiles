import errno
import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry


class SqliteConnection(Protocol):
    def execute(self, statement: str) -> None: ...


@dataclass(frozen=True, slots=True)
class _DatabaseIdentity:
    path: Path
    device: int
    inode: int


def create_daemon_engine(path: Path, busy_timeout_ms: int = 2_000) -> Engine:
    if busy_timeout_ms <= 0:
        raise ValueError("database busy timeout must be positive")
    identity = _prepare_database_file(path)
    return _create_validated_engine(identity, busy_timeout_ms)


def _create_validated_engine(identity: _DatabaseIdentity, busy_timeout_ms: int) -> Engine:
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(identity.path)), future=True)

    @event.listens_for(engine, "connect")
    def apply_pragmas(connection: SqliteConnection, _record: ConnectionPoolEntry) -> None:
        _validate_database_identity(identity)
        connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    return engine


def alembic_config(path: Path | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("file_template", "%%(year)d%%(month).2d%%(day).2d_%%(slug)s")
    if path is not None:
        identity = _prepare_database_file(path)
        engine = _create_validated_engine(identity, 5_000)
        config.set_main_option("sqlalchemy.url", str(URL.create("sqlite+pysqlite", database=str(identity.path))))
        config.attributes["connection"] = engine.connect()
        config.attributes["engine"] = engine
    return config


def migrate_daemon_db(path: Path) -> None:
    canonical_path = _configured_database_path(path)
    with _migration_lock(canonical_path):
        command.upgrade(alembic_config(canonical_path), "head")


def downgrade_daemon_db(path: Path) -> None:
    canonical_path = _configured_database_path(path)
    with _migration_lock(canonical_path):
        command.downgrade(alembic_config(canonical_path), "base")


def _configured_database_path(path: Path) -> Path:
    expanded_path = path.expanduser().absolute()
    if expanded_path.is_symlink():
        raise PermissionError(f"database file must not be a symbolic link: {expanded_path}")
    expanded_path.parent.mkdir(parents=True, exist_ok=True)
    return expanded_path.parent.resolve(strict=True) / expanded_path.name


def _prepare_database_file(path: Path) -> _DatabaseIdentity:
    canonical_path = _configured_database_path(path)
    directory = os.open(canonical_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    created = False
    try:
        try:
            descriptor = os.open(
                canonical_path.name,
                os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
        except FileNotFoundError:
            descriptor = os.open(
                canonical_path.name,
                os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory,
            )
            created = True
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise PermissionError(f"database file must not be a symbolic link: {canonical_path}") from error
            raise
        try:
            if created:
                os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            _validate_database_metadata(canonical_path, metadata)
            return _DatabaseIdentity(path=canonical_path, device=metadata.st_dev, inode=metadata.st_ino)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _validate_database_identity(identity: _DatabaseIdentity) -> None:
    try:
        descriptor = os.open(
            identity.path,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise PermissionError(f"database file must not be a symbolic link: {identity.path}") from error
        raise
    try:
        metadata = os.fstat(descriptor)
        _validate_database_metadata(identity.path, metadata)
        if (metadata.st_dev, metadata.st_ino) != (identity.device, identity.inode):
            raise PermissionError(f"database file changed after validation: {identity.path}")
    finally:
        os.close(descriptor)


def _validate_database_metadata(path: Path, metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise PermissionError(f"database must be a user-owned regular mode-0600 file: {path}")


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
