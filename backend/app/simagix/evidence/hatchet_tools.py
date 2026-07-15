from __future__ import annotations

from typing import Any, Literal

from backend.app.db.connection import db_conn
from backend.app.simagix.budget import RetrievalBudget

HATCHET_MCP_TOOL_NAMES: frozenset[str] = frozenset({
    "get_hatchet_slow_ops",
    "get_hatchet_log_examples",
    "get_hatchet_audit",
    "get_hatchet_connection_timeline",
})

_SNIPPET_CHARS = 500
SortBy = Literal["avg_ms", "total_ms"]


# ---------------------------------------------------------------------------
# Module-level helpers (absorbed from hatchet_summary + hatchet_readiness)
# ---------------------------------------------------------------------------

def hatchet_evidence_available(run_id: str) -> bool:
    """True when hatchet evidence has been ingested for this run."""
    with db_conn() as conn:
        cur = conn.execute(
            "SELECT 1 FROM evidence WHERE run_id = %s AND key = 'hatchet_meta' LIMIT 1",
            (run_id,),
        )
        return cur.fetchone() is not None


def load_hatchet_summary(run_id: str) -> dict[str, Any] | None:
    """Return the stored hatchet_summary JSONB or None if not yet ingested."""
    with db_conn() as conn:
        cur = conn.execute(
            "SELECT data FROM evidence WHERE run_id = %s AND key = 'hatchet_summary'",
            (run_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def build_hatchet_evidence_block(summary: dict[str, Any]) -> str:
    meta = summary.get("metadata", {})
    parts = [
        "You are reviewing tier-1 Hatchet log evidence (MongoDB JSON logs). "
        f"MongoDB {meta.get('mongodb_version', 'unknown')}, "
        f"module={meta.get('module', '?')}, "
        f"arch={meta.get('arch', '?')}, "
        f"os={meta.get('os', '?')}. "
        f"Log window: {meta.get('start', '?')} – {meta.get('end', '?')}. "
        f"Total log lines analysed: {meta.get('log_line_count', '?')}."
    ]
    marker_counts = summary.get("marker_counts", [])
    if marker_counts:
        parts.append(
            "Source file markers: "
            + ", ".join(
                f"[{m['marker']}]={m['count']}" for m in marker_counts
            )
        )
    return " ".join(parts)


class HatchetNotReadyError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def assert_hatchet_ready_for_phase2(workspace_root: Any, run_id: str) -> None:
    from backend.app.core.run_workspace import RunWorkspace
    from backend.app.jobs.catalog import hatchet_block_message, hatchet_blocks_phase2
    workspace = RunWorkspace(workspace_root)
    if not hatchet_blocks_phase2(workspace, run_id):
        return
    raise HatchetNotReadyError(hatchet_block_message(workspace, run_id))


# ---------------------------------------------------------------------------
# HatchetTools — replaces HatchetEvidenceTools (sqlite3 → typed Postgres tables)
# ---------------------------------------------------------------------------

_SORT_COLUMNS: dict[str, str] = {"avg_ms": "avg_ms", "total_ms": "total_ms"}


class HatchetTools:
    """Tier-2 Hatchet retrieval from the typed hatchet_* Postgres tables.

    Every source row from hatchet.db is available; filtering and sorting run
    in SQL at query time, matching the old direct-SQLite behaviour.
    """

    def __init__(self, run_id: str, *, budget: RetrievalBudget | None = None) -> None:
        self.run_id = run_id
        self.budget = budget
        summary = load_hatchet_summary(run_id)
        if summary is None:
            raise FileNotFoundError(f"Hatchet evidence not ingested for run: {run_id}")
        self._summary = summary

    def _consume(self, tool_name: str) -> None:
        if self.budget is not None:
            self.budget.consume_tool_call(tool_name)

    def get_hatchet_slow_ops(
        self,
        *,
        sort_by: SortBy = "avg_ms",
        limit: int = 20,
        collscan_only: bool = False,
    ) -> dict[str, Any]:
        self._consume("get_hatchet_slow_ops")
        limit = max(1, min(limit, 100))
        sort_col = _SORT_COLUMNS.get(sort_by, "avg_ms")
        where = "run_id = %s AND op IS NOT NULL AND op != ''"
        params: list[Any] = [self.run_id]
        if collscan_only:
            where += " AND (_index = 'COLLSCAN' OR filter LIKE '%%COLLSCAN%%')"
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT op, count, avg_ms, max_ms, total_ms, ns, _index, filter, marker"
                f" FROM hatchet_ops WHERE {where}"
                f" ORDER BY {sort_col} DESC NULLS LAST LIMIT %s",
                (*params, limit),
            ).fetchall()
        ops = [
            {
                "op": r[0], "count": r[1], "avg_ms": r[2], "max_ms": r[3],
                "total_ms": r[4], "ns": r[5], "index": r[6], "filter": r[7], "marker": r[8],
            }
            for r in rows
        ]
        return {
            "run_id": self.run_id,
            "hatchet_name": self._summary.get("hatchet_name"),
            "sort_by": sort_by,
            "collscan_only": collscan_only,
            "ops": ops,
        }

    def get_hatchet_log_examples(
        self,
        *,
        limit: int = 10,
        min_milli: float = 0,
    ) -> dict[str, Any]:
        self._consume("get_hatchet_log_examples")
        limit = max(1, min(limit, 25))
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT date, op, ns, milli, filter, message, marker"
                " FROM hatchet_logs"
                " WHERE run_id = %s AND milli IS NOT NULL AND milli >= %s"
                " ORDER BY milli DESC LIMIT %s",
                (self.run_id, min_milli, limit),
            ).fetchall()
        examples = []
        for date, op, ns, milli, filter_, message, marker in rows:
            msg = message or ""
            if len(msg) > _SNIPPET_CHARS:
                msg = msg[:_SNIPPET_CHARS] + "…"
            examples.append({
                "date": date,
                "op": op,
                "ns": ns,
                "milli": milli,
                "filter": filter_,
                "snippet": msg,
                "marker": marker,
            })
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
        self._consume("get_hatchet_audit")
        limit = max(1, min(limit, 100))
        where = "run_id = %s"
        params: list[Any] = [self.run_id]
        if audit_type:
            where += " AND type = %s"
            params.append(audit_type)
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT type, name, value FROM hatchet_audit WHERE {where}"
                f" ORDER BY value DESC NULLS LAST LIMIT %s",
                (*params, limit),
            ).fetchall()
        return {
            "run_id": self.run_id,
            "hatchet_name": self._summary.get("hatchet_name"),
            "audit_type": audit_type,
            "rows": [{"type": r[0], "name": r[1], "value": r[2]} for r in rows],
        }

    def get_hatchet_connection_timeline(self, *, limit: int = 48) -> dict[str, Any]:
        self._consume("get_hatchet_connection_timeline")
        limit = max(1, min(limit, 96))
        with db_conn() as conn:
            has_dates = conn.execute(
                "SELECT 1 FROM hatchet_clients WHERE run_id = %s AND date IS NOT NULL LIMIT 1",
                (self.run_id,),
            ).fetchone() is not None
            if has_dates:
                rows = conn.execute(
                    "SELECT SUBSTR(date, 1, 16) AS bucket,"
                    " SUM(accepted)::BIGINT, SUM(ended)::BIGINT"
                    " FROM hatchet_clients"
                    " WHERE run_id = %s AND (accepted > 0 OR ended > 0)"
                    " GROUP BY bucket ORDER BY bucket LIMIT %s",
                    (self.run_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ip AS bucket, SUM(accepted)::BIGINT, SUM(ended)::BIGINT"
                    " FROM hatchet_clients"
                    " WHERE run_id = %s AND (accepted > 0 OR ended > 0)"
                    " GROUP BY ip ORDER BY (SUM(accepted) + SUM(ended)) DESC LIMIT %s",
                    (self.run_id, limit),
                ).fetchall()
        return {
            "run_id": self.run_id,
            "hatchet_name": self._summary.get("hatchet_name"),
            "timeline": [
                {"bucket": r[0], "accepted": r[1], "ended": r[2]} for r in rows
            ],
        }
