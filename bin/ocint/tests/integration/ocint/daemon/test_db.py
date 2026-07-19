import stat
from pathlib import Path

from ocint.daemon.db import downgrade_daemon_db, migrate_daemon_db


def test_upgrade_downgrade_upgrade_occurs(tmp_path: Path) -> None:
    # GIVEN
    database = tmp_path / "control.sqlite"

    # WHEN
    migrate_daemon_db(database)
    downgrade_daemon_db(database)
    migrate_daemon_db(database)


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
