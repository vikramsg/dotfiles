import stat
from pathlib import Path

from ocint.daemon.db import create_daemon_engine, downgrade_daemon_db, migrate_daemon_db
from ocint.daemon.db.schema import metadata
from sqlalchemy import UniqueConstraint, inspect


def test_upgrade_downgrade_upgrade_matches_complete_metadata(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"

    # WHEN
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "github_issue",
        "github_issue_comment",
        "job",
    }
    engine.dispose()
    downgrade_daemon_db(database)
    engine = create_daemon_engine(database)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
    migrate_daemon_db(database)
    engine = create_daemon_engine(database)
    inspector = inspect(engine)

    # THEN
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "github_issue",
        "github_issue_comment",
        "job",
    }
    for table in metadata.sorted_tables:
        primary_key_columns = set(inspector.get_pk_constraint(table.name)["constrained_columns"])
        actual_columns = {
            column["name"]: (
                str(column["type"]),
                bool(column["nullable"]),
                int(column["name"] in primary_key_columns),
            )
            for column in inspector.get_columns(table.name)
        }
        expected_columns = {
            column.name: (
                column.type.compile(dialect=engine.dialect),
                column.nullable,
                int(column.primary_key),
            )
            for column in table.columns
        }
        assert actual_columns == expected_columns

        actual_foreign_keys = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys(table.name)
        }
        expected_foreign_keys = {
            (
                tuple(constraint.column_keys),
                constraint.referred_table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in table.foreign_key_constraints
        }
        assert actual_foreign_keys == expected_foreign_keys

        actual_unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
        expected_unique = {
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert actual_unique == expected_unique

        actual_indexes = {
            (item["name"], tuple(item["column_names"]), bool(item["unique"]))
            for item in inspector.get_indexes(table.name)
        }
        expected_indexes = {
            (index.name, tuple(column.name for column in index.columns), index.unique) for index in table.indexes
        }
        assert actual_indexes == expected_indexes
    engine.dispose()


def test_migration_secures_existing_database_without_recreating_it(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"
    migrate_daemon_db(database)
    inode = database.stat().st_ino
    database.chmod(0o644)

    # WHEN
    migrate_daemon_db(database)

    # THEN
    assert database.stat().st_ino == inode
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
