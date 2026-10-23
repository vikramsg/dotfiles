import sqlite3

import pytest
from ocint._sqlsafe import execute_readonly_query, normalize_select_sql


def test_normalize_select_sql_allows_single_select_or_with() -> None:
    assert normalize_select_sql(" SELECT 1; ") == "SELECT 1"
    assert normalize_select_sql("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")


@pytest.mark.parametrize(
    "sql",
    ["", "insert into x values (1)", "update x set id = 1", "delete from x", "drop table x", "select 1; select 2"],
)
def test_normalize_select_sql_rejects_mutating_or_multiple_statements(sql: str) -> None:
    with pytest.raises(ValueError, match=r"SQL query is required|Only"):
        normalize_select_sql(sql)


def test_execute_readonly_query_blocks_mutating_with_statement() -> None:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE item (id INTEGER)")
    con.execute("INSERT INTO item VALUES (1)")

    with pytest.raises((sqlite3.DatabaseError, ValueError)):
        execute_readonly_query(con, "WITH x AS (SELECT id FROM item) DELETE FROM item WHERE id IN (SELECT id FROM x)")

    assert con.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 1
