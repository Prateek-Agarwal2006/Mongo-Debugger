from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MAX_SLOW_OPS = 20
MAX_COLLSCAN = 30
MAX_SLOW_EXAMPLES = 10
SNIPPET_CHARS = 500
MAX_CONNECTION_BUCKETS = 24

COLLSCAN = "COLLSCAN"


def _rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query, params)
    return list(cur.fetchall())


def _hatchet_info(conn: sqlite3.Connection) -> sqlite3.Row | None:
    rows = _rows(conn, "SELECT name, merge, version, module, arch, os, start, end FROM hatchet LIMIT 1")
    return rows[0] if rows else None


def _table(name: str, suffix: str) -> str:
    return f"{name}{suffix}" if suffix.startswith("_") else f"{name}_{suffix}"


def _validate_table_name(name: str) -> str:
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid Hatchet table name: {name}")
    return name


def _table_columns(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    table = _validate_table_name(table)
    rows = _rows(conn, f"PRAGMA table_info({table})")
    return frozenset(str(row["name"]) for row in rows)


def query_connection_timeline(
    conn: sqlite3.Connection,
    clients_table: str,
    *,
    limit: int,
) -> list[sqlite3.Row]:
    """Hatchet clients tables vary: some have per-event ``date``, others only ``ip`` rollups."""
    table = _validate_table_name(clients_table)
    cols = _table_columns(conn, table)
    if "date" in cols:
        return _rows(
            conn,
            f"""
            SELECT SUBSTR(date, 1, 16) AS bucket, SUM(accepted) AS accepted, SUM(ended) AS ended
            FROM {table}
            WHERE accepted > 0 OR ended > 0
            GROUP BY bucket
            ORDER BY bucket
            LIMIT ?
            """,
            (limit,),
        )
    if "ip" in cols:
        return _rows(
            conn,
            f"""
            SELECT ip AS bucket, SUM(accepted) AS accepted, SUM(ended) AS ended
            FROM {table}
            WHERE accepted > 0 OR ended > 0
            GROUP BY ip
            ORDER BY (SUM(accepted) + SUM(ended)) DESC
            LIMIT ?
            """,
            (limit,),
        )
    return []


def export_hatchet_summary(
    db_path: Path,
    *,
    source_files: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    if not db_path.is_file():
        raise FileNotFoundError(f"Hatchet database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        info = _hatchet_info(conn)
        if info is None:
            raise ValueError("Hatchet registry table is empty")

        hatchet_name = str(info["name"])
        logs_table = hatchet_name
        ops_table = _table(hatchet_name, "_ops")
        audit_table = _table(hatchet_name, "_audit")
        clients_table = _table(hatchet_name, "_clients")
        drivers_table = _table(hatchet_name, "_drivers")

        top_avg = _rows(
            conn,
            f"""
            SELECT op, count, avg_ms, max_ms, total_ms, ns, _index, filter, marker
            FROM {ops_table}
            WHERE op != ''
            ORDER BY avg_ms DESC
            LIMIT ?
            """,
            (MAX_SLOW_OPS,),
        )
        top_total = _rows(
            conn,
            f"""
            SELECT op, count, avg_ms, max_ms, total_ms, ns, _index, filter, marker
            FROM {ops_table}
            WHERE op != ''
            ORDER BY total_ms DESC
            LIMIT ?
            """,
            (MAX_SLOW_OPS,),
        )
        collscan = _rows(
            conn,
            f"""
            SELECT op, count, avg_ms, max_ms, total_ms, ns, _index, filter, marker
            FROM {ops_table}
            WHERE _index = ? OR filter LIKE '%COLLSCAN%'
            ORDER BY total_ms DESC
            LIMIT ?
            """,
            (COLLSCAN, MAX_COLLSCAN),
        )
        slow_examples = _rows(
            conn,
            f"""
            SELECT date, op, ns, milli, filter, message, marker
            FROM {logs_table}
            WHERE milli IS NOT NULL AND milli > 0
            ORDER BY milli DESC
            LIMIT ?
            """,
            (MAX_SLOW_EXAMPLES,),
        )
        audit_rows = _rows(
            conn,
            f"""
            SELECT type, name, value
            FROM {audit_table}
            ORDER BY value DESC
            LIMIT 40
            """,
        )
        drivers = _rows(
            conn,
            f"""
            SELECT driver, version, COUNT(*) AS cnt
            FROM {drivers_table}
            WHERE driver != ''
            GROUP BY driver, version
            ORDER BY cnt DESC
            LIMIT 20
            """,
        )
        connection_timeline = query_connection_timeline(
            conn,
            clients_table,
            limit=MAX_CONNECTION_BUCKETS,
        )
        log_count = _rows(conn, f"SELECT COUNT(*) AS cnt FROM {logs_table}")[0]["cnt"]

        marker_counts = _rows(
            conn,
            f"SELECT marker, COUNT(*) AS cnt FROM {logs_table} GROUP BY marker ORDER BY marker",
        )

        return {
            "contract_version": "1.0.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "hatchet_name": hatchet_name,
            "merge": bool(info["merge"]),
            "metadata": {
                "mongodb_version": info["version"],
                "module": info["module"],
                "arch": info["arch"],
                "os": info["os"],
                "start": info["start"],
                "end": info["end"],
                "log_line_count": int(log_count),
            },
            "source_files": source_files,
            "marker_counts": [{"marker": row["marker"], "count": row["cnt"]} for row in marker_counts],
            "top_slow_ops_by_avg_ms": [_op_row(row) for row in top_avg],
            "top_slow_ops_by_total_ms": [_op_row(row) for row in top_total],
            "collscan_ops": [_op_row(row) for row in collscan],
            "audit_highlights": [
                {"type": row["type"], "name": row["name"], "value": row["value"]} for row in audit_rows
            ],
            "observed_drivers": [
                {"driver": row["driver"], "version": row["version"], "count": row["cnt"]} for row in drivers
            ],
            "slow_log_examples": [_slow_example(row) for row in slow_examples],
            "connection_timeline": [
                {"bucket": row["bucket"], "accepted": row["accepted"], "ended": row["ended"]}
                for row in connection_timeline
            ],
            "store_paths": {
                "hatchet_name": hatchet_name,
                "logs_table": logs_table,
                "ops_table": ops_table,
                "audit_table": audit_table,
                "clients_table": clients_table,
                "drivers_table": drivers_table,
            },
        }
    finally:
        conn.close()


def write_hatchet_artifacts(
    db_path: Path,
    out_dir: Path,
    *,
    source_files: list[dict[str, Any]],
    run_id: str,
    status_extra: dict[str, Any] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = export_hatchet_summary(db_path, source_files=source_files, run_id=run_id)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    status = {
        "run_id": run_id,
        "hatchet_name": summary["hatchet_name"],
        "source_files": source_files,
        "log_line_count": summary["metadata"]["log_line_count"],
        "marker_counts": summary["marker_counts"],
        "summary_path": str(summary_path.name),
        "db_path": "hatchet.db",
    }
    if status_extra:
        status.update(status_extra)
    (out_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return summary_path


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


def _slow_example(row: sqlite3.Row) -> dict[str, Any]:
    message = row["message"] or ""
    if len(message) > SNIPPET_CHARS:
        message = message[:SNIPPET_CHARS] + "…"
    return {
        "date": row["date"],
        "op": row["op"],
        "ns": row["ns"],
        "milli": row["milli"],
        "filter": row["filter"],
        "snippet": message,
        "marker": row["marker"],
    }
