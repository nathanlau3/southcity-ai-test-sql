"""Seed data termuat dan graph bisa di-compile."""

def test_schema_seed_loaded(run_sql):
    assert run_sql("SELECT COUNT(*) FROM Units") == [(12,)]
    assert run_sql("SELECT COUNT(*) FROM Sales_Contracts") == [(6,)]


def test_graph_compiles():
    from text2sql.agent.graph import build_graph

    graph = build_graph()
    nodes = set(graph.get_graph().nodes)
    assert {"input_guard", "generate_sql", "validate_sql", "apply_rbac", "execute_sql"} <= nodes
