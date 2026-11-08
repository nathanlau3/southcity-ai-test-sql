"""Validasi SQL hasil LLM secara struktural (AST sqlglot) sebelum menyentuh database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import sqlglot
from sqlglot import exp

from text2sql.db.catalog import QUERYABLE_TABLES

ErrorKind = Literal["syntax", "security"]


@dataclass
class GuardResult:
    ok: bool
    sql: str | None = None
    tables: list[str] = field(default_factory=list)
    # "syntax" boleh di-retry oleh LLM, "security" langsung ditolak.
    error_kind: ErrorKind | None = None
    message: str | None = None


FORBIDDEN_NODE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
    exp.Command,  # statement yang tidak dikenali sqlglot: VACUUM, EXPLAIN, REPLACE INTO
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Into,  # SELECT ... INTO tabel_baru
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Analyze,  # menulis tabel sqlite_stat*
)

FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {"load_extension", "readfile", "writefile", "fts3_tokenizer"}
)

# CTE tidak boleh memakai nama tabel asli, supaya tidak lolos dari allowlist dan RBAC.
_REAL_TABLE_NAMES = {t.lower() for t in QUERYABLE_TABLES} | {"system_users"}


def _reject(kind: ErrorKind, message: str) -> GuardResult:
    return GuardResult(ok=False, error_kind=kind, message=message)


def validate_sql(
    sql: str,
    *,
    allowed_tables: set[str],
    max_rows: int,
    dialect: str = "sqlite",
) -> GuardResult:
    try:
        parsed = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.SqlglotError as e:
        return _reject("syntax", f"SQL tidak valid: {e}")

    # Komentar setelah titik koma terakhir terbaca sebagai node Semicolon.
    statements = [s for s in parsed if s is not None and not isinstance(s, exp.Semicolon)]
    if not statements:
        return _reject("syntax", "SQL kosong.")
    if len(statements) != 1:
        return _reject(
            "security", f"Hanya satu statement yang diizinkan, ditemukan {len(statements)}."
        )
    stmt = statements[0]

    # Dicek sebelum tipe root, supaya DROP/PRAGMA tidak terklasifikasi sebagai syntax error.
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            return _reject("security", f"Operasi terlarang terdeteksi: {type(node).__name__}.")
        if isinstance(node, exp.Anonymous) and node.name.lower() in FORBIDDEN_FUNCTIONS:
            return _reject("security", f"Fungsi terlarang: {node.name}.")

    # sqlglot cukup longgar: "SELEC * FRM" tidak error, tapi terbaca sebagai ekspresi lain.
    if not isinstance(stmt, exp.Query):
        return _reject(
            "syntax",
            f"Bukan query SELECT yang valid (terbaca sebagai {type(stmt).__name__}). "
            "Tulis ulang sebagai satu query SELECT.",
        )

    allowed_lower = {t.lower() for t in allowed_tables}
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    if cte_names & _REAL_TABLE_NAMES:
        return _reject("security", "Nama CTE tidak boleh sama dengan nama tabel asli.")

    used_tables: set[str] = set()
    for table in stmt.find_all(exp.Table):
        if table.db or table.catalog:
            return _reject("security", f"Prefix skema/database tidak diizinkan: {table.sql()}.")
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in allowed_lower:
            return _reject("security", f"Akses ke tabel '{table.name}' tidak diizinkan.")
        used_tables.add(table.name)

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    else:
        value = limit.expression
        is_small_int = (
            isinstance(value, exp.Literal) and value.is_int and int(value.this) <= max_rows
        )
        if not is_small_int:
            stmt = stmt.limit(max_rows)

    return GuardResult(ok=True, sql=stmt.sql(dialect=dialect), tables=sorted(used_tables))


def _debug_print_ast(sql: str, dialect: str = "sqlite") -> None:
    for stmt in sqlglot.parse(sql, read=dialect):
        print(repr(stmt))
        print("-" * 60)
