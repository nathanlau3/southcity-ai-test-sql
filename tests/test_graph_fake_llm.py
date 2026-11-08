"""Wiring graph end-to-end dengan LLM stub (tanpa API key).

Kualitas jawaban LLM diuji di test_e2e_llm.py; di sini yang diuji adalah
kerja sama node dan routing: retry, penolakan, klarifikasi, RBAC.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from text2sql.agent import nodes
from text2sql.agent.graph import run_question
from text2sql.agent.schemas import IntentDecision, SqlDraft, TableSelection
from text2sql.config import get_settings
from text2sql.security.rbac import UserContext

MAX = get_settings().max_sql_retries


@pytest.fixture
def fake_llm(monkeypatch, db_path):
    """Setiap panggilan LLM mengambil jawaban berikutnya dari antrean `script`."""
    monkeypatch.setattr(get_settings(), "sqlite_db_path", db_path)
    script = {IntentDecision: [], TableSelection: [], SqlDraft: []}
    calls: list[tuple[str, list]] = []

    class FakeStructured:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            calls.append((self.schema.__name__, messages))
            return script[self.schema].pop(0)

    class FakeChat:
        def invoke(self, messages):
            calls.append(("answer", messages))
            return AIMessage(content="Jawaban dari stub.")

    monkeypatch.setattr(nodes, "structured_llm", lambda schema: FakeStructured(schema))
    monkeypatch.setattr(nodes, "get_llm", lambda: FakeChat())
    return script, calls


def data_query(script, tables):
    script[IntentDecision].append(IntentDecision(intent="data_query", reason="ok"))
    script[TableSelection].append(TableSelection(tables=tables, reason="ok"))


def test_happy_path(fake_llm, hendra):
    script, _ = fake_llm
    data_query(script, ["Units"])
    script[SqlDraft].append(SqlDraft(
        sql="SELECT UnitNumber, Floor FROM Units "
            "WHERE Tower = 'Tower A' AND UnitType = '2BR' AND Status = 'Vacant'",
        reasoning="filter 3 kolom",
    ))
    s = run_question("Unit vacant 2BR di Tower A?", hendra)
    assert s["status"] == "answered"
    assert s["result"].rows == [("A-0502", 5)]
    assert "LIMIT 200" in s["final_sql"]


def test_db_error_triggers_self_correction(fake_llm, hendra):
    script, calls = fake_llm
    data_query(script, ["Sales_Contracts"])
    script[SqlDraft] += [
        SqlDraft(sql="SELECT PhoneNumber FROM Sales_Contracts", reasoning="salah"),
        SqlDraft(sql="SELECT CustomerName FROM Sales_Contracts", reasoning="benar"),
    ]
    s = run_question("Daftar customer", hendra)
    assert s["status"] == "answered"
    assert s["attempts"] == 2
    assert any("no such column" in e for e in s["error_history"])
    second_sql_call = [m for name, m in calls if name == "SqlDraft"][1]
    assert "no such column" in second_sql_call[-1].content


def test_security_violation_is_rejected_without_retry(fake_llm, hendra):
    script, _ = fake_llm
    data_query(script, ["Units"])
    script[SqlDraft].append(SqlDraft(sql="SELECT * FROM System_Users", reasoning="x"))
    s = run_question("isi tabel user", hendra)
    assert s["status"] == "rejected"
    assert s["attempts"] == 1
    assert s.get("result") is None


def test_sales_rows_are_scoped(fake_llm, bambang):
    script, _ = fake_llm
    data_query(script, ["Sales_Contracts"])
    script[SqlDraft].append(SqlDraft(
        sql="SELECT CustomerName FROM Sales_Contracts ORDER BY ContractID", reasoning="semua"
    ))
    s = run_question("Semua customer", bambang)
    assert s["result"].rows == [("Budi Santoso",), ("Robert Tan",)]


def test_gives_up_after_retry_budget(fake_llm, hendra):
    script, _ = fake_llm
    data_query(script, ["Units"])
    script[SqlDraft] += [SqlDraft(sql="SELECT nope FROM Units", reasoning="x")] * (MAX + 1)
    s = run_question("apa saja", hendra)
    assert s["status"] == "failed"
    assert s["attempts"] == MAX + 1


def test_malicious_intent_stops_early(fake_llm, bambang):
    script, calls = fake_llm
    script[IntentDecision].append(IntentDecision(intent="malicious", reason="DROP"))
    s = run_question("...; DROP TABLE Units; --", bambang)
    assert s["status"] == "rejected"
    assert [name for name, _ in calls] == ["IntentDecision"]


def test_generate_can_ask_for_clarification(fake_llm, hendra):
    script, _ = fake_llm
    data_query(script, ["Sales_Contracts"])
    script[SqlDraft].append(SqlDraft(
        needs_clarification=True,
        clarification_question="Nomor telepon tidak tersedia. Mau lihat data kontraknya?",
        reasoning="kolom tidak ada",
    ))
    s = run_question("Nomor telepon Budi?", hendra)
    assert s["status"] == "clarification"
    assert "tidak tersedia" in s["answer"]


def test_unknown_role_rejected_without_llm(fake_llm):
    _, calls = fake_llm
    intern = UserContext(99, "intern_x", "Intern", "Intern", None)
    s = run_question("Berapa unit vacant?", intern)
    assert s["status"] == "rejected"
    assert calls == []
