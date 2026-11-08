from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from text2sql.agent import nodes
from text2sql.agent.state import AgentState
from text2sql.config import get_settings
from text2sql.security.rbac import UserContext


def _retry_budget_left(state: AgentState) -> bool:
    # Total percobaan maksimum = 1 + max_sql_retries.
    return state.get("attempts", 0) <= get_settings().max_sql_retries


def route_after_input_guard(state: AgentState) -> Literal["data_query", "clarify", "reject"]:
    intent = state.get("intent")
    if intent == "data_query":
        return "data_query"
    if intent == "ambiguous":
        return "clarify"
    return "reject"


def route_after_generate(state: AgentState) -> Literal["validate", "clarify", "give_up"]:
    if state.get("candidate_sql"):
        return "validate"
    if state.get("clarification_question"):
        return "clarify"
    return "give_up"


def route_after_validate(state: AgentState) -> Literal["rbac", "retry", "reject", "give_up"]:
    kind = state.get("last_error_kind")
    if kind == "security":
        return "reject"
    if state.get("validated_sql") and kind is None:
        return "rbac"
    if kind == "syntax":
        return "retry" if _retry_budget_left(state) else "give_up"
    return "reject"


def route_after_rbac(state: AgentState) -> Literal["execute", "reject"]:
    return "execute" if state.get("final_sql") else "reject"


def route_after_execute(state: AgentState) -> Literal["summarize", "retry", "give_up"]:
    if state.get("result") is not None:
        return "summarize"
    if state.get("last_error_kind") == "db" and _retry_budget_left(state):
        return "retry"
    return "give_up"


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("input_guard", nodes.input_guard)
    g.add_node("link_schema", nodes.link_schema)
    g.add_node("generate_sql", nodes.generate_sql)
    g.add_node("validate_sql", nodes.validate_sql_node)
    g.add_node("apply_rbac", nodes.apply_rbac_node)
    g.add_node("execute_sql", nodes.execute_sql_node)
    g.add_node("summarize_answer", nodes.summarize_answer)
    g.add_node("respond_clarification", nodes.respond_clarification)
    g.add_node("respond_rejection", nodes.respond_rejection)
    g.add_node("respond_failure", nodes.respond_failure)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges(
        "input_guard",
        route_after_input_guard,
        {
            "data_query": "link_schema",
            "clarify": "respond_clarification",
            "reject": "respond_rejection",
        },
    )
    g.add_edge("link_schema", "generate_sql")
    g.add_conditional_edges(
        "generate_sql",
        route_after_generate,
        {
            "validate": "validate_sql",
            "clarify": "respond_clarification",
            "give_up": "respond_failure",
        },
    )
    g.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {
            "rbac": "apply_rbac",
            "retry": "generate_sql",
            "reject": "respond_rejection",
            "give_up": "respond_failure",
        },
    )
    g.add_conditional_edges(
        "apply_rbac",
        route_after_rbac,
        {"execute": "execute_sql", "reject": "respond_rejection"},
    )
    g.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {
            "summarize": "summarize_answer",
            "retry": "generate_sql",
            "give_up": "respond_failure",
        },
    )
    for terminal in (
        "summarize_answer",
        "respond_clarification",
        "respond_rejection",
        "respond_failure",
    ):
        g.add_edge(terminal, END)

    return g.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_question(question: str, user: UserContext) -> AgentState:
    s = get_settings()
    initial: AgentState = {
        "question": question,
        "user": user,
        "today": s.today().isoformat(),
        "attempts": 0,
        "error_history": [],
        "trace": [],
    }
    return get_graph().invoke(initial)


if __name__ == "__main__":
    print(get_graph().get_graph().draw_mermaid())
