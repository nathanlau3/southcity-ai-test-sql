"""State yang mengalir antar node LangGraph."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from text2sql.db.connection import QueryResult
from text2sql.security.rbac import UserContext

Intent = Literal["data_query", "ambiguous", "malicious", "out_of_scope"]
Status = Literal["answered", "clarification", "rejected", "failed"]


class AgentState(TypedDict, total=False):
    # Input
    question: str
    user: UserContext  # dari sesi login, bukan dari teks pertanyaan
    today: str  # YYYY-MM-DD

    # Input guard
    intent: Intent
    intent_reason: str

    # Schema linking
    relevant_tables: list[str]
    schema_context: str

    # Generate SQL + retry
    candidate_sql: str | None
    attempts: int  # jumlah pemanggilan generate_sql
    last_error: str | None
    last_error_kind: Literal["syntax", "security", "db"] | None
    error_history: Annotated[list[str], operator.add]

    # Guard & RBAC
    validated_sql: str | None
    final_sql: str | None  # setelah rewrite RBAC, ini yang dieksekusi

    # Execute
    result: QueryResult | None

    # Output
    status: Status
    answer: str
    clarification_question: str | None

    # Log per node untuk panel debug di UI.
    trace: Annotated[list[str], operator.add]
