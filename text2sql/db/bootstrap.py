"""Membangun file SQLite dari schema.sql (DDL + seed data).

Koneksi di sini punya hak tulis dan hanya dipakai untuk setup. Pertanyaan user
selalu dieksekusi lewat koneksi read-only di connection.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def build_database(schema_path: Path, db_path: Path, *, force: bool = False) -> Path:
    """Jalankan schema.sql ke file SQLite baru. Idempotent kecuali `force=True`."""
    if db_path.exists() and not force:
        return db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()

    tmp_path.replace(db_path)  # atomic, tidak ada file DB setengah jadi
    return db_path


if __name__ == "__main__":
    from text2sql.config import get_settings

    s = get_settings()
    path = build_database(s.schema_sql_path, s.sqlite_db_path, force=True)
    print(f"Database dibangun ulang: {path}")
