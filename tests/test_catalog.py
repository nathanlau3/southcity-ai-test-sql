"""Katalog skema untuk schema linking."""

from __future__ import annotations

import sqlite3

import pytest

from text2sql.db.catalog import QUERYABLE_TABLES, TABLE_NOTES, get_table_ddl, render_schema_context


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    yield c
    c.close()


def test_ddl_is_introspected(conn):
    assert "CREATE TABLE Units" in get_table_ddl(conn, "Units")


def test_all_table_notes_are_filled():
    missing = [t for t in QUERYABLE_TABLES if "TODO" in TABLE_NOTES.get(t, "TODO")]
    assert not missing, f"Deskripsi tabel belum diisi: {missing}"


def test_context_contains_only_requested_tables(conn):
    ctx = render_schema_context(conn, ["Units", "Sales_Contracts"])
    assert "CREATE TABLE Units" in ctx
    assert "CREATE TABLE Sales_Contracts" in ctx
    assert "CREATE TABLE Payments_Received" not in ctx


def test_system_users_never_reaches_prompt(conn):
    ctx = render_schema_context(conn, ["Units", "System_Users"])
    assert "CREATE TABLE System_Users" not in ctx
