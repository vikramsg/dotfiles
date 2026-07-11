import sqlite3
from pathlib import Path

from ocint.opencode.repository import OpenCodeRepository
from tests.support.opencode_db import create_opencode_db


def test_usage_part_batches_push_time_window_and_parse_batches(tmp_path: Path) -> None:
    # GIVEN an OpenCode repository with a known patch part timestamp
    db_path = create_opencode_db(tmp_path / "opencode.db")
    with sqlite3.connect(db_path) as connection:
        start_ms = int(connection.execute("SELECT timeCreated FROM part WHERE id = 'p-primary-patch'").fetchone()[0])
    repository = OpenCodeRepository(db_path)

    # WHEN a one-row bounded batch is loaded
    batches = list(repository.usage_part_batches(start_ms=start_ms, end_ms=start_ms + 1, batch_size=1))

    # THEN the repository pushed the window down and parsed the part
    assert [[part.id for part in batch] for batch in batches] == [["p-primary-patch"]]
    assert batches[0][0].data.type == "file.patch"
