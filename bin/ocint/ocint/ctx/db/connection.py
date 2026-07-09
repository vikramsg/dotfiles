from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session

from ocint.ctx.config import CTX_DB_BUSY_TIMEOUT_MS

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
CTX_ALEMBIC_FILE_TEMPLATE = "%%(year)d%%(month).2d%%(day).2d_%%(slug)s"


def create_ctx_engine(db_path: Path) -> Engine:
    url = URL.create("sqlite+pysqlite", database=str(db_path))
    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _apply_ctx_sqlite_pragmas(dbapi_connection: Any, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={CTX_DB_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

    return engine


def migrate_ctx_db(db_path: Path) -> None:
    """Run Alembic against the ocint ctx DB only, creating its parent as needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(_ctx_alembic_config(db_path), "head")


def current_ctx_head_revision() -> str:
    """Return the single Alembic head from the ctx DB migration package."""
    heads = ScriptDirectory.from_config(_ctx_alembic_config()).get_heads()
    if len(heads) != 1:
        raise ValueError(f"ocint ctx migrations must expose exactly one Alembic head; found {len(heads)}")
    return heads[0]


def _ctx_alembic_config(db_path: Path | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if db_path is not None:
        config.set_main_option("sqlalchemy.url", str(URL.create("sqlite+pysqlite", database=str(db_path))))
    # Keep generated ctx migration filenames on the agreed date+slug convention;
    # the stable identifier is the date-prefixed slug, not an extra sequence token.
    config.set_main_option("file_template", CTX_ALEMBIC_FILE_TEMPLATE)
    return config


@contextmanager
def ctx_session(db_path: Path, *, commit: bool) -> Iterator[Session]:
    engine = create_ctx_engine(db_path)
    session = Session(engine, future=True)
    try:
        yield session
        if commit:
            session.commit()
    except BaseException:
        # KeyboardInterrupt and SystemExit must also leave the SQLAlchemy session usable for rollback.
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
