"""Fungsi routing dan self-correction loop, diuji dengan state palsu."""

from __future__ import annotations

from text2sql.agent.graph import (
    route_after_execute,
    route_after_generate,
    route_after_rbac,
    route_after_validate,
)
from text2sql.config import get_settings
from text2sql.db.connection import QueryResult

MAX = get_settings().max_sql_retries  # default 3 -> total 4 percobaan


def test_generate_goes_to_validate():
    assert route_after_generate({"candidate_sql": "SELECT 1"}) == "validate"


def test_generate_asks_clarification():
    state = {"candidate_sql": None, "clarification_question": "Customer yang mana?"}
    assert route_after_generate(state) == "clarify"


def test_valid_sql_goes_to_rbac():
    assert route_after_validate({"validated_sql": "SELECT 1", "attempts": 1}) == "rbac"


def test_security_violation_is_never_retried():
    state = {"last_error_kind": "security", "last_error": "DROP", "attempts": 1}
    assert route_after_validate(state) == "reject"


def test_syntax_error_is_retried_while_budget_left():
    state = {"last_error_kind": "syntax", "last_error": "x", "attempts": 1}
    assert route_after_validate(state) == "retry"


def test_syntax_error_gives_up_when_budget_exhausted():
    state = {"last_error_kind": "syntax", "last_error": "x", "attempts": MAX + 1}
    assert route_after_validate(state) == "give_up"


def test_rbac_routes():
    assert route_after_rbac({"final_sql": "SELECT 1"}) == "execute"
    assert route_after_rbac({"final_sql": None, "last_error_kind": "security"}) == "reject"


def test_db_error_is_retried_at_least_twice():
    """Soal: minimal 2x retry. Percobaan ke-1 dan ke-2 yang gagal harus di-retry."""
    for attempts in (1, 2):
        state = {"last_error_kind": "db", "last_error": "no such column", "attempts": attempts}
        assert route_after_execute(state) == "retry"


def test_db_error_gives_up_eventually():
    state = {"last_error_kind": "db", "last_error": "x", "attempts": MAX + 1}
    assert route_after_execute(state) == "give_up"


def test_success_goes_to_summarize():
    state = {"result": QueryResult(columns=["n"], rows=[(1,)]), "attempts": 1}
    assert route_after_execute(state) == "summarize"
