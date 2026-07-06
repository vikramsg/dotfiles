from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def create_ctx_engine(db_path: Path) -> Engine:
    url = URL.create("sqlite+pysqlite", database=str(db_path))
    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


def migrate_ctx_db(db_path: Path) -> None:
    """Run Alembic against the ocint ctx DB only, creating its parent as needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", str(URL.create("sqlite+pysqlite", database=str(db_path))))
    # Keep generated ctx migration filenames on the agreed date+slug convention;
    # the stable identifier is the date-prefixed slug, not an extra sequence token.
    config.set_main_option("file_template", "%%(year)d%%(month).2d%%(day).2d_%%(slug)s")
    command.upgrade(config, "head")


@contextmanager
def ctx_session(db_path: Path, *, commit: bool) -> Iterator[Session]:
    engine = create_ctx_engine(db_path)
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
