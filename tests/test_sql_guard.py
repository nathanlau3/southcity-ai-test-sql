"""AST guard."""

from __future__ import annotations

import pytest

from text2sql.security.rbac import ALL_BUSINESS_TABLES, POLICIES
from text2sql.security.sql_guard import validate_sql

FINANCE_TABLES = set(ALL_BUSINESS_TABLES)
SALES_TABLES = set(POLICIES["Sales"].allowed_tables)


def check(sql: str, tables: set[str] = FINANCE_TABLES):
    return validate_sql(sql, allowed_tables=tables, max_rows=200)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT UnitNumber, Floor FROM Units WHERE Status = 'Vacant'",
        "SELECT c.CustomerName FROM Sales_Contracts c JOIN Units u ON u.UnitID = c.UnitID",
        "WITH x AS (SELECT ContractID FROM Sales_Contracts) SELECT * FROM x",
        "SELECT CustomerName FROM Sales_Contracts UNION SELECT UnitNumber FROM Units",
        "SELECT 'DROP TABLE Units' AS cuma_teks",  # string literal, bukan perintah
        "SELECT * FROM units",  # nama tabel case-insensitive
    ],
)
def test_valid_select_is_accepted(sql):
    r = check(sql)
    assert r.ok, r.message
    assert r.error_kind is None


def test_limit_is_added_when_missing():
    r = check("SELECT * FROM Units")
    assert r.ok
    assert "LIMIT 200" in r.sql.upper()


def test_smaller_limit_is_kept():
    r = check("SELECT * FROM Units LIMIT 5")
    assert r.ok
    assert "LIMIT 5" in r.sql.upper()


@pytest.mark.parametrize(
    "sql",
    [
        # Security test #1 dari soal (query piggybacking)
        "SELECT CustomerName FROM Sales_Contracts WHERE BookingDate LIKE '2026-01%'; DROP TABLE Units; --",
        "DROP TABLE Units",
        "DELETE FROM Units",
        "UPDATE Units SET Status = 'Sold'",
        "INSERT INTO Units (UnitID) VALUES (99)",
        "ALTER TABLE Units ADD COLUMN x INT",
        "CREATE TABLE x (id INT)",
        "PRAGMA table_info(Units)",
        "ATTACH DATABASE '/tmp/evil.db' AS evil",
        # Security test #2 dari soal (System_Users)
        "SELECT * FROM System_Users",
        "SELECT u.* FROM Units u JOIN System_Users s ON 1 = 1",
        "SELECT * FROM (SELECT * FROM System_Users) AS t",
        "WITH s AS (SELECT * FROM System_Users) SELECT * FROM s",
        # Lain-lain
        "SELECT load_extension('evil')",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM main.Units",
    ],
)
def test_dangerous_sql_is_rejected_as_security(sql):
    r = check(sql)
    assert not r.ok
    assert r.error_kind == "security", r.message


def test_sales_cannot_read_payments_received():
    r = check("SELECT SUM(PaidAmount) FROM Payments_Received", tables=SALES_TABLES)
    assert not r.ok
    assert r.error_kind == "security"


@pytest.mark.parametrize(
    "sql",
    [
        "SELEC * FRM Units",
        "SELECT * FROM Units WHERE (Status = 'Vacant'",
    ],
)
def test_broken_sql_is_retryable_syntax_error(sql):
    r = check(sql)
    assert not r.ok
    assert r.error_kind == "syntax", r.message
