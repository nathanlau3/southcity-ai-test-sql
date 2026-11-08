"""Koneksi read-only dan eksekusi query."""

from __future__ import annotations

import sqlite3

import pytest

from text2sql.db.connection import QueryExecutionError, execute_select, open_readonly_connection


def run(sql, db_path, max_rows=200, timeout_s=5.0):
    return execute_select(sql, db_path=db_path, max_rows=max_rows, timeout_s=timeout_s)


def test_select_returns_columns_and_rows(db_path):
    r = run("SELECT UnitNumber, Floor FROM Units WHERE UnitID = 2", db_path)
    assert r.columns == ["UnitNumber", "Floor"]
    assert r.rows == [("A-0502", 5)]
    assert r.truncated is False


def test_result_is_truncated(db_path):
    r = run("SELECT * FROM Units", db_path, max_rows=5)
    assert len(r.rows) == 5
    assert r.truncated is True


@pytest.mark.parametrize(
    "sql", ["DELETE FROM Units", "DROP TABLE Units", "UPDATE Units SET Floor = 0"]
)
def test_connection_cannot_write(db_path, run_sql, sql):
    conn = open_readonly_connection(db_path)
    try:
        with pytest.raises(sqlite3.Error):
            conn.execute(sql)
    finally:
        conn.close()
    assert run_sql("SELECT COUNT(*) FROM Units") == [(12,)]


def test_db_error_is_wrapped_with_useful_message(db_path):
    with pytest.raises(QueryExecutionError, match="no such column"):
        run("SELECT PhoneNumber FROM Sales_Contracts", db_path)


def test_runaway_query_times_out(db_path):
    infinite = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
    with pytest.raises(QueryExecutionError):
        run(infinite, db_path, timeout_s=0.3)
