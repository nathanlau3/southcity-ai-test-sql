from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from text2sql.db.bootstrap import build_database
from text2sql.security.rbac import UserContext

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    """Database SQLite baru dari schema.sql, khusus untuk sesi test."""
    path = tmp_path_factory.mktemp("db") / "southcity_test.db"
    return build_database(ROOT / "schema.sql", path)


@pytest.fixture
def run_sql(db_path):
    """Eksekusi SQL mentah (read-only) untuk memverifikasi hasil rewrite RBAC."""

    def _run(sql: str) -> list[tuple]:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    return _run


@pytest.fixture
def bambang() -> UserContext:
    return UserContext(1, "sales_bambang", "Bambang Pamungkas", "Sales", 101)


@pytest.fixture
def dewi() -> UserContext:
    return UserContext(2, "sales_dewi", "Dewi Lestari", "Sales", 102)


@pytest.fixture
def hendra() -> UserContext:
    return UserContext(4, "finance_hendra", "Hendra Setiawan", "Finance", None)
