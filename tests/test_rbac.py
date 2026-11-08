from __future__ import annotations

import pytest

from text2sql.security.rbac import AccessDenied, UserContext, apply_rbac, load_user_context


# load_user_context
def test_load_sales_user(db_path):
    u = load_user_context("sales_bambang", db_path)
    assert (u.role, u.assigned_agent_id) == ("Sales", 101)


def test_load_finance_user(db_path):
    u = load_user_context("finance_hendra", db_path)
    assert (u.role, u.assigned_agent_id) == ("Finance", None)


@pytest.mark.parametrize("username", ["tidak_ada", "sales_bambang' OR '1'='1"])
def test_unknown_user_is_denied(db_path, username):
    with pytest.raises(AccessDenied):
        load_user_context(username, db_path)


# apply_rbac
def test_finance_sees_everything(run_sql, hendra):
    assert run_sql(apply_rbac("SELECT COUNT(*) FROM Sales_Contracts", hendra)) == [(6,)]


def test_sales_sees_only_own_contracts(run_sql, bambang):
    sql = "SELECT ContractID FROM Sales_Contracts ORDER BY ContractID"
    assert run_sql(apply_rbac(sql, bambang)) == [(101,), (103,)]


def test_alias_and_join_still_work(run_sql, bambang):
    sql = (
        "SELECT c.CustomerName, u.UnitNumber FROM Sales_Contracts AS c "
        "JOIN Units AS u ON u.UnitID = c.UnitID ORDER BY c.ContractID"
    )
    assert run_sql(apply_rbac(sql, bambang)) == [("Budi Santoso", "A-0101"), ("Robert Tan", "A-1508")]


def test_horizontal_escalation_returns_nothing(run_sql, bambang):
    """Security test #3 dari soal: Bambang menanyakan customer milik Dewi."""
    sql = "SELECT CustomerName, TotalPrice FROM Sales_Contracts WHERE CustomerName = 'Siti Rahma'"
    assert run_sql(apply_rbac(sql, bambang)) == []


def test_owner_can_see_own_customer(run_sql, dewi):
    sql = "SELECT CustomerName FROM Sales_Contracts WHERE CustomerName = 'Siti Rahma'"
    assert run_sql(apply_rbac(sql, dewi)) == [("Siti Rahma",)]


def test_child_table_scoped_via_contract(run_sql, bambang):
    sql = (
        "SELECT SUM(PenaltyAmount - WaiverAmount - PaidPenalty) FROM Late_Fee_Penalties "
        "WHERE PenaltyStatus = 'Outstanding'"
    )
    assert run_sql(apply_rbac(sql, bambang)) == [(600000,)]  # Finance: 4.800.000


def test_payment_schedules_scoped(run_sql, bambang):
    sql = "SELECT DISTINCT ContractID FROM Payment_Schedules ORDER BY ContractID"
    assert run_sql(apply_rbac(sql, bambang)) == [(101,), (103,)]


def test_units_are_not_scoped(run_sql, bambang):
    assert run_sql(apply_rbac("SELECT COUNT(*) FROM Units", bambang)) == [(12,)]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM (SELECT * FROM Sales_Contracts) AS x",
        "SELECT COUNT(*) FROM Units WHERE UnitID IN (SELECT UnitID FROM Sales_Contracts)",
        "WITH mine AS (SELECT * FROM Sales_Contracts) SELECT COUNT(*) FROM mine",
        "SELECT COUNT(*) FROM sales_contracts",
    ],
    ids=["subquery-from", "subquery-where", "cte", "lowercase"],
)
def test_nested_references_are_scoped(run_sql, bambang, sql):
    assert run_sql(apply_rbac(sql, bambang)) == [(2,)]


def test_union_both_sides_scoped(run_sql, bambang):
    sql = (
        "SELECT CustomerName FROM Sales_Contracts WHERE ContractID = 102 "
        "UNION SELECT CustomerName FROM Sales_Contracts WHERE ContractID = 105"
    )
    assert run_sql(apply_rbac(sql, bambang)) == []


def test_unknown_role_is_denied():
    intern = UserContext(99, "intern_x", "Intern", "Intern", None)
    with pytest.raises(AccessDenied):
        apply_rbac("SELECT * FROM Units", intern)


def test_sales_without_agent_id_is_denied():
    broken = UserContext(98, "sales_x", "Sales Tanpa Agent", "Sales", None)
    with pytest.raises(AccessDenied):
        apply_rbac("SELECT * FROM Sales_Contracts", broken)
