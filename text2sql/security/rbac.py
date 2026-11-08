"""Role-based access control: identitas dari sesi, allowlist tabel, dan isolasi baris."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class UserContext:
    user_id: int
    username: str
    full_name: str
    role: str
    assigned_agent_id: int | None  # hanya terisi untuk role Sales


RowScope = Literal["all", "own_contracts"]


@dataclass(frozen=True)
class RolePolicy:
    allowed_tables: frozenset[str]
    row_scope: RowScope
    hidden_columns: frozenset[str] = frozenset()


ALL_BUSINESS_TABLES = frozenset(
    {"Units", "Sales_Contracts", "Payment_Schedules", "Payments_Received", "Late_Fee_Penalties"}
)

POLICIES: dict[str, RolePolicy] = {
    # Sales tidak mendapat Payments_Received (mutasi kas finance), lihat D1 di ARCHITECTURE.md.
    "Sales": RolePolicy(
        allowed_tables=frozenset(
            {"Units", "Sales_Contracts", "Payment_Schedules", "Late_Fee_Penalties"}
        ),
        row_scope="own_contracts",
    ),
    "Finance": RolePolicy(allowed_tables=ALL_BUSINESS_TABLES, row_scope="all"),
    # Tidak dijelaskan di soal; diputuskan read-only semua tabel bisnis (D2).
    "Auditor": RolePolicy(allowed_tables=ALL_BUSINESS_TABLES, row_scope="all"),
}

# Units sengaja tidak dibatasi: ketersediaan unit boleh dilihat semua Sales.
OWN_CONTRACT_SCOPED_TABLES: dict[str, str] = {
    "Sales_Contracts": "direct",
    "Payment_Schedules": "via_contract",
    "Payments_Received": "via_contract",
    "Late_Fee_Penalties": "via_contract",
}

_SCOPED_BY_LOWER: dict[str, str] = {name.lower(): name for name in OWN_CONTRACT_SCOPED_TABLES}


class AccessDenied(Exception):
    """Pesannya aman untuk ditampilkan ke user."""


def get_policy(role: str) -> RolePolicy:
    try:
        return POLICIES[role]
    except KeyError:
        raise AccessDenied(f"Role '{role}' tidak memiliki akses ke asisten data.") from None


def list_active_users(db_path: Path) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT Username, FullName, Role FROM System_Users WHERE IsActive = 1 ORDER BY UserID"
        ).fetchall()
    finally:
        conn.close()


def load_user_context(username: str, db_path: Path) -> UserContext:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT UserID, Username, FullName, Role, AssignedAgentID"
            " FROM System_Users WHERE Username = ? AND IsActive = 1",
            (username,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise AccessDenied("User tidak ditemukan atau nonaktif.")

    user_id, uname, full_name, role, agent_id = row
    if role == "Sales" and agent_id is None:
        raise AccessDenied("Akun Sales ini belum terhubung ke AgentID. Hubungi admin.")

    return UserContext(
        user_id=int(user_id),
        username=uname,
        full_name=full_name,
        role=role,
        assigned_agent_id=int(agent_id) if agent_id is not None else None,
    )


def _scoped_subquery(table: str, agent_id: int) -> exp.Select:
    if OWN_CONTRACT_SCOPED_TABLES[table] == "direct":
        condition = f"SalesAgentID = {agent_id}"
    else:
        condition = (
            "ContractID IN (SELECT ContractID FROM Sales_Contracts "
            f"WHERE SalesAgentID = {agent_id})"
        )
    return exp.select("*").from_(table).where(condition)


def apply_rbac(sql: str, user: UserContext, *, dialect: str = "sqlite") -> str:
    """Ganti setiap tabel yang dibatasi dengan subquery terfilter, alias tetap sama.

    SELECT c.CustomerName FROM Sales_Contracts AS c
    -> SELECT c.CustomerName FROM (SELECT * FROM Sales_Contracts WHERE SalesAgentID = 101) AS c
    """
    policy = get_policy(user.role)
    if policy.row_scope == "all":
        return sql

    if user.assigned_agent_id is None:
        raise AccessDenied("Akun ini tidak memiliki AgentID; akses data ditolak.")
    agent_id = int(user.assigned_agent_id)

    tree = sqlglot.parse_one(sql, read=dialect)
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}

    # List dulu, supaya Table di dalam subquery yang baru disisipkan tidak ikut diproses.
    for table in list(tree.find_all(exp.Table)):
        lowered = table.name.lower()
        if lowered in cte_names or lowered not in _SCOPED_BY_LOWER:
            continue
        canonical = _SCOPED_BY_LOWER[lowered]
        table.replace(_scoped_subquery(canonical, agent_id).subquery(table.alias_or_name))

    return tree.sql(dialect=dialect)


def describe_access(user: UserContext) -> str:
    who = f"User: {user.full_name} (username {user.username}, role {user.role}"
    if user.assigned_agent_id is not None:
        who += f", AgentID {user.assigned_agent_id}"
    who += ")."

    try:
        policy = get_policy(user.role)
    except AccessDenied:
        return who + " Role ini tidak memiliki akses data apa pun."

    lines = [who, f"Tabel yang boleh diakses: {', '.join(sorted(policy.allowed_tables))}."]
    if policy.row_scope == "own_contracts":
        lines.append(
            f"Hanya boleh melihat kontrak dengan SalesAgentID = {user.assigned_agent_id} "
            "beserta jadwal tagihan dan denda kontrak tersebut. Data Units (ketersediaan "
            "unit) boleh dilihat semua. Filter baris diterapkan otomatis oleh sistem."
        )
    else:
        lines.append("Boleh melihat seluruh baris pada tabel di atas.")

    denied = sorted(ALL_BUSINESS_TABLES - policy.allowed_tables)
    if denied:
        lines.append(f"Tidak boleh mengakses: {', '.join(denied)}.")
    lines.append("Tabel akun/kredensial (System_Users) tidak bisa diakses siapa pun.")
    return "\n".join(lines)
