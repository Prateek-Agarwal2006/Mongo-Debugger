from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

from backend.app.core.run_workspace import RunWorkspace
from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.hatchet_export import query_connection_timeline
from backend.app.simagix.hatchet_summary import load_hatchet_summary

HATCHET_MCP_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_hatchet_slow_ops",
        "get_hatchet_log_examples",
        "get_hatchet_audit",
        "get_hatchet_connection_timeline",
    }
)

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SNIPPET_CHARS = 500
COLLSCAN = "COLLSCAN"

SortBy = Literal["avg_ms", "total_ms"]


def hatchet_evidence_available(workspace_root: Path, run_id: str) -> bool:
    workspace = RunWorkspace(workspace_root)
    return workspace.hatchet_summary_ready(run_id) and workspace.hatchet_db_path(run_id).is_file()


def _validate_table(name: str) -> str:
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid Hatchet table name: {name}")
    return name


def _rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query, params)
    return list(cur.fetchall())


def _op_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "op": row["op"],
        "count": row["count"],
        "avg_ms": row["avg_ms"],
        "max_ms": row["max_ms"],
        "total_ms": row["total_ms"],
        "ns": row["ns"],
        "index": row["_index"],
        "filter": row["filter"],
        "marker": row["marker"],
    }


class HatchetEvidenceTools:
    """Tier-2 Hatchet retrieval over run-scoped hatchet.db (v2 MCP / ADK tools)."""

    def __init__(
        self,
        workspace_root: Path,
        run_id: str,
        *,
        budget: RetrievalBudget | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.run_id = run_id
        self.budget = budget
        self._workspace = RunWorkspace(self.workspace_root)
        self._summary = load_hatchet_summary(self.workspace_root, run_id)
        if self._summary is None:
            raise FileNotFoundError(f"Hatchet summary not found for run: {run_id}")
        self._db_path = self._workspace.hatchet_db_path(run_id)
        if not self._db_path.is_file():
            raise FileNotFoundError(f"Hatchet database not found: {self._db_path}")
        store_paths = self._summary.get("store_paths", {})
        self._ops_table = _validate_table(str(store_paths.get("ops_table", "")))
        self._logs_table = _validate_table(str(store_paths.get("logs_table", "")))
        self._audit_table = _validate_table(str(store_paths.get("audit_table", "")))
        self._clients_table = _validate_table(str(store_paths.get("clients_table", "")))

    def _consume(self, tool_name: str) -> None:
        if self.budget is not None:
            self.budget.consume_tool_call(tool_name)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    def get_hatchet_slow_ops(
        self,
        *,
        sort_by: SortBy = "avg_ms",
        limit: int = 20,
        collscan_only: bool = False,
    ) -> dict[str, Any]:
        """Return slow-operation rollups from Hatchet ops table (deeper slice than summary.json)."""
        self._consume("get_hatchet_slow_ops")
        order_col = "total_ms" if sort_by == "total_ms" else "avg_ms"
        limit = max(1, min(limit, 100))
        if collscan_only:
            query = f"""
                SELECT op, count, avg_ms, max_ms, total_ms, ns, _index, filter, marker
                FROM {self._ops_table}
                WHERE op != '' AND (_index = ? OR filter LIKE '%COLLSCAN%')
                ORDER BY {order_col} DESC
                LIMIT ?
            """
            params: tuple[Any, ...] = (COLLSCAN, limit)
        else:
            query = f"""
                SELECT op, count, avg_ms, max_ms, total_ms, ns, _index, filter, marker
                FROM {self._ops_table}
                WHERE op != ''
                ORDER BY {order_col} DESC
                LIMIT ?
            """
            params = (limit,)
        conn = self._connect()
        try:
            rows = _rows(conn, query, params)
        finally:
            conn.close()
        return {
            "run_id": self.run_id,
            "hatchet_name": self._summary.get("hatchet_name"),
            "sort_by": sort_by,
            "collscan_only": collscan_only,
            "ops": [_op_row(row) for row in rows],
        }

    def get_hatchet_log_examples(
        self,
        *,
        limit: int = 10,
        min_milli: float = 0,
    ) -> dict[str, Any]:
        """Return slowest log line examples with capped message snippets."""
        self._consume("get_hatchet_log_examples")
        limit = max(1, min(limit, 25))
        conn = self._connect()
        try:
            rows = _rows(
                conn,
                f"""
                SELECT date, op, ns, milli, filter, message, marker
                FROM {self._logs_table}
                WHERE milli IS NOT NULL AND milli >= ?
                ORDER BY milli DESC
                LIMIT ?
                """,
                (min_milli, limit),
            )
        finally:
            conn.close()
        examples: list[dict[str, Any]] = []
        for row in rows:
            message = row["message"] or ""
            if len(message) > _SNIPPET_CHARS:
                message = message[:_SNIPPET_CHARS] + "…"
            examples.append(
                {
                    "date": row["date"],
                    "op": row["op"],
                    "ns": row["ns"],
                    "milli": row["milli"],
                    "filter": row["filter"],
                    "snippet": message,
                    "marker": row["marker"],
                }
            )
        return {
            "run_id": self.run_id,
            "hatchet_name": self._summary.get("hatchet_name"),
            "min_milli": min_milli,
            "examples": examples,
        }

    def get_hatchet_audit(
        self,
        *,
        audit_type: str | None = None,
        limit: int = 40,
    ) -> dict[str, Any]:
        """Return audit rollups (exceptions, namespaces, drivers, etc.) from Hatchet audit table."""
        self._consume("get_hatchet_audit")
        limit = max(1, min(limit, 100))
        conn = self._connect()
        try:
            if audit_type:
                rows = _rows(
                    conn,
                    f"""
                    SELECT type, name, value
                    FROM {self._audit_table}
                    WHERE type = ?
                    ORDER BY value DESC
                    LIMIT ?
                    """,
                    (audit_type, limit),
                )
            else:
                rows = _rows(
                    conn,
                    f"""
                    SELECT type, name, value
                    FROM {self._audit_table}
                    ORDER BY value DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
        finally:
            conn.close()
        return {
            "run_id": self.run_id,
            "hatchet_name": self._summary.get("hatchet_name"),
            "audit_type": audit_type,
            "rows": [{"type": row["type"], "name": row["name"], "value": row["value"]} for row in rows],
        }

    def get_hatchet_connection_timeline(self, *, limit: int = 48) -> dict[str, Any]:
        """Return accepted/ended connection counts per minute bucket."""
        self._consume("get_hatchet_connection_timeline")
        limit = max(1, min(limit, 96))
        conn = self._connect()
        try:
            rows = query_connection_timeline(conn, self._clients_table, limit=limit)
        finally:
            conn.close()
        return {
            "run_id": self.run_id,
            "hatchet_name": self._summary.get("hatchet_name"),
            "timeline": [
                {"bucket": row["bucket"], "accepted": row["accepted"], "ended": row["ended"]}
                for row in rows
            ],
        }
