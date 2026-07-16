from pathlib import Path

from ocint.daemon.db import create_daemon_engine, downgrade_daemon_db, migrate_daemon_db
from ocint.daemon.db.schema import metadata
from pydantic import BaseModel, ConfigDict
from sqlalchemy import inspect


class TableSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    columns: list[str]


def test_single_daemon_migration_round_trips_final_metadata_schema(tmp_path: Path) -> None:
    # GIVEN a fresh daemon database path and the final metadata contract
    path = tmp_path / "control.sqlite"
    expected = [
        TableSnapshot(name=table.name, columns=[column.name for column in table.columns])
        for table in sorted(metadata.sorted_tables, key=lambda item: item.name)
    ]

    # WHEN the squashed initial revision upgrades the database
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    inspector = inspect(engine)
    first = [
        TableSnapshot(name=name, columns=[str(column["name"]) for column in inspector.get_columns(name)])
        for name in sorted(metadata.tables)
    ]

    # THEN physical schema exactly matches metadata, and downgrade/upgrade reproduces it
    assert first == expected
    engine.dispose()
    downgrade_daemon_db(path)
    migrate_daemon_db(path)
    engine = create_daemon_engine(path)
    inspector = inspect(engine)
    second = [
        TableSnapshot(name=name, columns=[str(column["name"]) for column in inspector.get_columns(name)])
        for name in sorted(metadata.tables)
    ]
    assert second == expected
    engine.dispose()
