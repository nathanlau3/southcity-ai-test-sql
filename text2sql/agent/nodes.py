"""Node LangGraph. Setiap node menerima AgentState dan mengembalikan field yang berubah saja."""

from __future__ import annotations

from text2sql.agent import prompts
from text2sql.agent.llm import get_llm, structured_llm
from text2sql.agent.schemas import IntentDecision, SqlDraft, TableSelection
from text2sql.agent.state import AgentState
from text2sql.config import get_settings
from text2sql.db import catalog
from text2sql.db.connection import (
    QueryExecutionError,
    QueryResult,
    execute_select,
    open_readonly_connection,
)
from text2sql.security import rbac, sql_guard

PREVIEW_ROWS = 50


def input_guard(state: AgentState) -> dict:
    user = state["user"]

    # Role tanpa kebijakan langsung ditolak, tidak perlu memanggil LLM.
    try:
        rbac.get_policy(user.role)
    except rbac.AccessDenied as e:
        return {
            "intent": "out_of_scope",
            "intent_reason": str(e),
            "trace": [f"input_guard: role ditolak ({e})"],
        }

    access = rbac.describe_access(user)
    msgs = prompts.build_input_guard_messages(state["question"], access)
    decision: IntentDecision = structured_llm(IntentDecision).invoke(msgs)
    return {
        "intent": decision.intent,
        "intent_reason": decision.reason,
        "clarification_question": decision.clarification_question,
        "trace": [f"input_guard: {decision.intent} ({decision.reason})"],
    }


def link_schema(state: AgentState) -> dict:
    settings = get_settings()
    policy = rbac.get_policy(state["user"].role)
    allowed = [t for t in catalog.QUERYABLE_TABLES if t in policy.allowed_tables]

    table_catalog = "\n".join(f"- {t}: {catalog.TABLE_NOTES[t]}" for t in allowed)
    msgs = prompts.build_schema_link_messages(state["question"], table_catalog)
    selection: TableSelection = structured_llm(TableSelection).invoke(msgs)

    # Output LLM disaring lagi ke allowlist role.
    allowed_by_lower = {t.lower(): t for t in allowed}
    tables: list[str] = []
    for name in selection.tables:
        canonical = allowed_by_lower.get(name.strip().lower())
        if canonical and canonical not in tables:
            tables.append(canonical)
    if not tables:
        tables = allowed

    conn = open_readonly_connection(settings.sqlite_db_path)
    try:
        schema_context = catalog.render_schema_context(conn, tables)
    finally:
        conn.close()

    return {
        "relevant_tables": tables,
        "schema_context": schema_context,
        "trace": [f"link_schema: {tables} ({selection.reason})"],
    }


def generate_sql(state: AgentState) -> dict:
    settings = get_settings()
    attempts = state.get("attempts", 0) + 1

    msgs = prompts.build_sql_gen_messages(
        question=state["question"],
        dialect=settings.sql_dialect,
        today=state["today"],
        access_summary=rbac.describe_access(state["user"]),
        schema_context=state["schema_context"],
        previous_sql=state.get("candidate_sql"),
        error=state.get("last_error"),
    )
    draft: SqlDraft = structured_llm(SqlDraft).invoke(msgs)

    sql = (draft.sql or "").strip() or None
    clarification = None
    if draft.needs_clarification or sql is None:
        sql = None
        clarification = draft.clarification_question

    return {
        "attempts": attempts,
        "candidate_sql": sql,
        "clarification_question": clarification,
        # Bersihkan hasil percobaan sebelumnya.
        "validated_sql": None,
        "final_sql": None,
        "result": None,
        "last_error": None,
        "last_error_kind": None,
        "trace": [f"generate_sql #{attempts}: {sql or '(klarifikasi)'}"],
    }


def validate_sql_node(state: AgentState) -> dict:
    settings = get_settings()
    policy = rbac.get_policy(state["user"].role)
    result = sql_guard.validate_sql(
        state["candidate_sql"],
        allowed_tables=set(policy.allowed_tables),
        max_rows=settings.max_result_rows,
        dialect=settings.sql_dialect,
    )
    if result.ok:
        return {
            "validated_sql": result.sql,
            "trace": [f"validate_sql: OK, tabel={result.tables}"],
        }
    return {
        "validated_sql": None,
        "last_error": result.message,
        "last_error_kind": result.error_kind,
        "error_history": [f"[{result.error_kind}] {result.message}"],
        "trace": [f"validate_sql: gagal [{result.error_kind}] {result.message}"],
    }


def apply_rbac_node(state: AgentState) -> dict:
    settings = get_settings()
    try:
        final_sql = rbac.apply_rbac(
            state["validated_sql"], state["user"], dialect=settings.sql_dialect
        )
    except rbac.AccessDenied as e:
        return {
            "final_sql": None,
            "last_error": str(e),
            "last_error_kind": "security",
            "trace": [f"apply_rbac: ditolak ({e})"],
        }
    return {"final_sql": final_sql, "trace": ["apply_rbac: filter baris terpasang"]}


def execute_sql_node(state: AgentState) -> dict:
    settings = get_settings()
    try:
        result = execute_select(
            state["final_sql"],
            db_path=settings.sqlite_db_path,
            max_rows=settings.max_result_rows,
            timeout_s=settings.query_timeout_seconds,
        )
    except QueryExecutionError as e:
        # Saat retry, LLM hanya menerima pesan error dan candidate_sql miliknya
        # sendiri, bukan final_sql hasil rewrite RBAC.
        return {
            "result": None,
            "last_error": str(e),
            "last_error_kind": "db",
            "error_history": [f"[db] {e}"],
            "trace": [f"execute_sql: error {e}"],
        }
    return {
        "result": result,
        "trace": [f"execute_sql: {len(result.rows)} baris ({result.meta.get('elapsed_ms')} ms)"],
    }


def _fmt_cell(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _rows_preview(result: QueryResult, limit: int = PREVIEW_ROWS) -> str:
    if not result.rows:
        return "(0 baris)"
    lines = [
        "| " + " | ".join(result.columns) + " |",
        "|" + "---|" * len(result.columns),
    ]
    for row in result.rows[:limit]:
        lines.append("| " + " | ".join(_fmt_cell(v) for v in row) + " |")
    if len(result.rows) > limit or result.truncated:
        shown = min(limit, len(result.rows))
        lines.append(f"(Catatan: hasil terpotong, hanya {shown} baris pertama.)")
    return "\n".join(lines)


def summarize_answer(state: AgentState) -> dict:
    result: QueryResult = state["result"]
    msgs = prompts.build_answer_messages(
        state["question"],
        state["validated_sql"],
        _rows_preview(result),
    )
    reply = get_llm().invoke(msgs)
    return {
        "status": "answered",
        "answer": reply.text,
        "trace": [f"summarize_answer: {len(result.rows)} baris diringkas"],
    }


def respond_clarification(state: AgentState) -> dict:
    question = state.get("clarification_question") or (
        "Pertanyaan Anda belum cukup spesifik. Bisa dijelaskan lebih detail "
        "(mis. nama customer, nomor unit, atau periode waktunya)?"
    )
    return {
        "status": "clarification",
        "answer": question,
        "trace": ["respond_clarification"],
    }


def respond_rejection(state: AgentState) -> dict:
    # Sengaja generik, tidak menjelaskan aturan keamanan mana yang dilanggar.
    return {
        "status": "rejected",
        "answer": (
            "Maaf, permintaan ini tidak dapat diproses. Asisten ini hanya melayani "
            "pertanyaan baca-data (read-only) sesuai hak akses akun Anda."
        ),
        "trace": [f"respond_rejection: {state.get('intent_reason') or state.get('last_error')}"],
    }


def respond_failure(state: AgentState) -> dict:
    return {
        "status": "failed",
        "answer": (
            "Maaf, saya belum berhasil menyusun kueri yang valid untuk pertanyaan ini "
            f"setelah {state.get('attempts', 0)} percobaan. Coba ubah kalimat pertanyaannya."
        ),
        "trace": ["respond_failure"],
    }
