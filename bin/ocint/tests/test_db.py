import sqlite3

import pytest

from ocint._db import open_readonly_connection

from tests.fixtures.opencode_db import create_opencode_db


def test_open_readonly_connection_allows_reads_and_rejects_writes(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")

    con = open_readonly_connection(db_path)
    try:
        assert con.execute("SELECT COUNT(*) FROM part").fetchone()[0] == 3
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("INSERT INTO part VALUES ('x', 'm', 's', 0, 0, '{}')")
    finally:
        con.close()


def test_open_readonly_connection_rejects_missing_and_memory_db(tmp_path) -> None:
    with pytest.raises(ValueError, match=":memory:"):
        open_readonly_connection(":memory:")
    with pytest.raises(FileNotFoundError, match="OpenCode DB does not exist"):
        open_readonly_connection(tmp_path / "missing.db")
