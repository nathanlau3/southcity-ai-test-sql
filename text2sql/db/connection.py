"""Eksekusi SQL lewat koneksi SQLite read-only."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool = False
    meta: dict = field(default_factory=dict)

    def as_records(self) -> list[dict]:
        return [dict(zip(self.columns, r)) for r in self.rows]


class QueryExecutionError(Exception):
    """Error dari database. Pesannya dikirim balik ke LLM saat retry."""


_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}
_DENIED_TABLES = {"system_users"}


def _authorizer(action, arg1, arg2, dbname, source):
    if action == sqlite3.SQLITE_READ and (arg1 or "").lower() in _DENIED_TABLES:
        return sqlite3.SQLITE_DENY
    if action in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def open_readonly_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    # Harus setelah PRAGMA, karena authorizer juga menolak PRAGMA.
    conn.set_authorizer(_authorizer)
    return conn


def execute_select(sql: str, *, db_path: Path, max_rows: int, timeout_s: float) -> QueryResult:
    conn = open_readonly_connection(db_path)
    started = time.monotonic()
    deadline = started + timeout_s

    def _stop_if_too_slow() -> bool:
        return time.monotonic() > deadline

    conn.set_progress_handler(_stop_if_too_slow, 10_000)
    try:
        cursor = conn.execute(sql)
        columns = [d[0] for d in (cursor.description or [])]
        rows = cursor.fetchmany(max_rows + 1)
        return QueryResult(
            columns=columns,
            rows=rows[:max_rows],
            truncated=len(rows) > max_rows,
            meta={"elapsed_ms": round((time.monotonic() - started) * 1000, 1)},
        )
    except sqlite3.Error as e:
        if time.monotonic() > deadline:
            raise QueryExecutionError(
                f"Query dibatalkan karena melebihi batas waktu {timeout_s} detik. "
                "Sederhanakan query-nya (hindari CROSS JOIN atau rekursi tanpa batas)."
            ) from e
        raise QueryExecutionError(str(e)) from e
    finally:
        conn.close()
