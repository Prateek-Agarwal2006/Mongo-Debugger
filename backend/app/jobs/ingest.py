from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from backend.app.core.run_workspace import RunWorkspace
from backend.app.db.connection import db_conn

_FTDC_EVIDENCE_KEYS: dict[str, str] = {
    "manifest": "manifest.json",
    "executive_context": "llm/executive_context.json",
    "findings": "diagnosis/findings.json",
    "anomaly_timeline": "diagnosis/anomaly_timeline.json",
    "activity_summary": "diagnosis/activity_summary.json",
    "assessment": "assessment/assessment.json",
    "formulas": "assessment/formulas.json",
    "bundle_index": "bundle_index.json",
    "validation": "validation.json",
    "fallback_index": "llm/fallback_retrieval_index.json",
}


def ingest_pipeline_run(workspace_root: Path, run_id: str) -> None:
    """Read ftdc outputs from temp disk and load into Postgres (metrics + evidence tables)."""
    workspace = RunWorkspace(workspace_root)
    bundle_dir = workspace.resolve_exports_dir(run_id)
    # Evidence first (own txn) so findings are visible while metrics COPY still runs.
    with db_conn() as conn:
        _ingest_evidence_files(conn, run_id, bundle_dir)
    with db_conn() as conn:
        _ingest_time_series(conn, run_id, bundle_dir)
    _ingest_raw_file_index(workspace_root, run_id)
    _ingest_raw_path_catalog(workspace_root, run_id)


def ingest_pipeline_evidence_only(workspace_root: Path, run_id: str) -> None:
    """Ingest only the JSON evidence blobs (no time series). Used by tests to seed quickly."""
    workspace = RunWorkspace(workspace_root)
    bundle_dir = workspace.resolve_exports_dir(run_id)
    with db_conn() as conn:
        _ingest_evidence_files(conn, run_id, bundle_dir)


def ingest_hatchet_run(workspace_root: Path, run_id: str) -> None:
    """Read hatchet.db from temp disk and load into Postgres evidence table."""
    workspace = RunWorkspace(workspace_root)
    db_path = workspace.hatchet_db_path(run_id)
    if not db_path.is_file():
        raise FileNotFoundError(f"Hatchet database not found: {db_path}")
    source_files = _source_file_entries(workspace, run_id)
    with sqlite3.connect(str(db_path)) as sqlite_conn:
        sqlite_conn.row_factory = sqlite3.Row
        with db_conn() as pg_conn:
            _ingest_hatchet_sqlite(pg_conn, sqlite_conn, run_id, source_files)


# ---------------------------------------------------------------------------
# FTDC helpers
# ---------------------------------------------------------------------------

def _ingest_evidence_files(conn: Any, run_id: str, bundle_dir: Path) -> None:
    for key, rel in _FTDC_EVIDENCE_KEYS.items():
        path = bundle_dir / rel
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s)"
            " ON CONFLICT (run_id, key) DO UPDATE SET data = EXCLUDED.data",
            (run_id, key, json.dumps(data)),
        )


def _ingest_raw_file_index(workspace_root: Path, run_id: str) -> None:
    """Run ftdc-slice --mode index on uploaded FTDC files; upsert raw_file_index rows."""
    import shutil
    from backend.app.db.raw_files import build_raw_file_index

    workspace = RunWorkspace(workspace_root)
    diag_dir = workspace.resolve_upload_diagnostic_dir(run_id)
    if not diag_dir.is_dir():
        return

    ftdc_paths = sorted(
        p for p in diag_dir.iterdir()
        if p.is_file() and p.name.startswith("metrics.")
    )
    if not ftdc_paths:
        return

    # Prefer binary on PATH (worker pod /usr/local/bin); fall back to local build.
    ftdc_slice_bin = shutil.which("ftdc-slice") or str(
        workspace_root / "simagix-workspace/repos/mongo-ftdc/ftdc-slice"
    )
    with db_conn() as conn:
        build_raw_file_index(conn, run_id, "ftdc", ftdc_paths, ftdc_slice_bin)


def _ingest_raw_path_catalog(workspace_root: Path, run_id: str) -> None:
    """Run ftdc-slice --mode catalog on last FTDC file; store catalog + prefix map in evidence."""
    workspace = RunWorkspace(workspace_root)
    diag_dir = workspace.resolve_upload_diagnostic_dir(run_id)
    if not diag_dir.is_dir():
        return

    ftdc_paths = sorted(
        p for p in diag_dir.iterdir()
        if p.is_file() and p.name.startswith("metrics.")
    )
    if not ftdc_paths:
        return

    ftdc_slice_bin = shutil.which("ftdc-slice") or str(
        workspace_root / "simagix-workspace/repos/mongo-ftdc/ftdc-slice"
    )
    try:
        result = subprocess.run(
            [ftdc_slice_bin, "--mode", "catalog", str(ftdc_paths[-1])],
            capture_output=True, text=True, timeout=300,
        )
    except (FileNotFoundError, OSError):
        return
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"ftdc-slice --mode catalog timed out after 300s on {ftdc_paths[-1].name}"
        ) from exc
    if not result.stdout.strip():
        return
    try:
        catalog = json.loads(result.stdout)
    except json.JSONDecodeError:
        return

    # Group paths by top-level segment to produce the prefix map.
    prefix_map: dict[str, list[str]] = {}
    for path in catalog.get("paths", []):
        prefix = path.split("/")[0]
        prefix_map.setdefault(prefix, []).append(path)

    with db_conn() as conn:
        conn.execute(
            "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s::jsonb)"
            " ON CONFLICT (run_id, key) DO UPDATE SET data = EXCLUDED.data",
            (run_id, "raw_path_catalog", json.dumps(catalog)),
        )
        conn.execute(
            "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s::jsonb)"
            " ON CONFLICT (run_id, key) DO UPDATE SET data = EXCLUDED.data",
            (run_id, "raw_path_prefix_map", json.dumps(prefix_map)),
        )


def _ingest_time_series(conn: Any, run_id: str, bundle_dir: Path) -> None:
    """Replace metrics for this run via Postgres COPY (write-once per Phase 1).

    Row-wise INSERT…ON CONFLICT is far too slow for multi-million-point FTDC
    exports; DELETE + COPY matches the replace semantics we want on retry.
    """
    ts_file = bundle_dir / "normalized/time_series.jsonl.gz"
    if not ts_file.exists():
        return

    conn.execute("DELETE FROM metrics WHERE run_id = %s", (run_id,))
    with conn.cursor() as cur:
        with cur.copy("COPY metrics (run_id, name, ts, value) FROM STDIN") as copy:
            with gzip.open(ts_file, "rt", encoding="utf-8") as fh:
                for line in fh:
                    rec = json.loads(line)
                    name = rec.get("target", "")
                    if not name:
                        continue
                    for value, raw_ts in rec.get("datapoints", []):
                        ts_ms = raw_ts if raw_ts > 1_000_000_000_000 else raw_ts * 1000
                        copy.write_row((run_id, name, float(ts_ms), value))


# ---------------------------------------------------------------------------
# Hatchet helpers
# ---------------------------------------------------------------------------

# PG destination table -> (sqlite table suffix, PG columns).  Every source row and
# column is copied; the column list is intersected with what the SQLite file
# actually has, so schema variants across hatchet versions are tolerated.
_HATCHET_TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "hatchet_logs": (
        "",
        ("id", "date", "severity", "component", "context", "msg", "plan", "type",
         "ns", "message", "op", "filter", "_index", "milli", "reslen", "appname", "marker"),
    ),
    "hatchet_ops": (
        "_ops",
        ("op", "count", "avg_ms", "max_ms", "total_ms", "ns", "_index", "reslen", "filter", "marker"),
    ),
    "hatchet_audit": ("_audit", ("type", "name", "value")),
    "hatchet_clients": (
        "_clients",
        ("id", "ip", "port", "date", "conns", "accepted", "ended", "context", "marker"),
    ),
    "hatchet_drivers": ("_drivers", ("id", "ip", "driver", "version", "marker")),
}

_NUL = "\x00"


def _ingest_hatchet_sqlite(
    pg_conn: Any,
    sqlite_conn: sqlite3.Connection,
    run_id: str,
    source_files: list[dict[str, Any]],
) -> None:
    cur = sqlite_conn.execute(
        "SELECT name, merge, version, module, arch, os, start, end FROM hatchet LIMIT 1"
    )
    info = cur.fetchone()
    if info is None:
        return

    hatchet_name = str(info["name"])

    meta: dict[str, Any] = {
        "hatchet_name": hatchet_name,
        "merge": bool(info["merge"]),
        "metadata": {
            "mongodb_version": info["version"],
            "module": info["module"],
            "arch": info["arch"],
            "os": info["os"],
            "start": info["start"],
            "end": info["end"],
        },
        "source_files": source_files,
    }
    _upsert(pg_conn, run_id, "hatchet_meta", meta)

    for pg_table, (suffix, pg_columns) in _HATCHET_TABLES.items():
        _copy_full_table(pg_conn, sqlite_conn, run_id, f"{hatchet_name}{suffix}", pg_table, pg_columns)

    log_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {hatchet_name}").fetchone()[0]
    marker_rows = sqlite_conn.execute(
        f"SELECT marker, COUNT(*) AS cnt FROM {hatchet_name} GROUP BY marker ORDER BY marker"
    ).fetchall()

    summary: dict[str, Any] = {
        "contract_version": "1.0.0",
        "run_id": run_id,
        "hatchet_name": hatchet_name,
        "merge": bool(info["merge"]),
        "metadata": meta["metadata"] | {"log_line_count": int(log_count)},
        "source_files": source_files,
        "marker_counts": [{"marker": r[0], "count": r[1]} for r in marker_rows],
    }
    _upsert(pg_conn, run_id, "hatchet_summary", summary)


def _copy_full_table(
    pg_conn: Any,
    sqlite_conn: sqlite3.Connection,
    run_id: str,
    src_table: str,
    dst_table: str,
    pg_columns: tuple[str, ...],
) -> None:
    """Stream every row of a SQLite table into its PG twin via COPY (idempotent per run)."""
    src_cols = {row[1] for row in sqlite_conn.execute(f"PRAGMA table_info({src_table})")}
    if not src_cols:
        return
    cols = [c for c in pg_columns if c in src_cols]
    if not cols:
        return

    pg_conn.execute(f"DELETE FROM {dst_table} WHERE run_id = %s", (run_id,))
    col_list = ", ".join(cols)
    src_cursor = sqlite_conn.execute(f"SELECT {col_list} FROM {src_table}")
    with pg_conn.cursor() as pg_cur:
        with pg_cur.copy(f"COPY {dst_table} (run_id, {col_list}) FROM STDIN") as copy:
            for row in src_cursor:
                copy.write_row(
                    (run_id, *(v.replace(_NUL, "") if isinstance(v, str) else v for v in row))
                )


def _upsert(pg_conn: Any, run_id: str, key: str, data: Any) -> None:
    pg_conn.execute(
        "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s)"
        " ON CONFLICT (run_id, key) DO UPDATE SET data = EXCLUDED.data",
        (run_id, key, json.dumps(data)),
    )


def _source_file_entries(workspace: RunWorkspace, run_id: str) -> list[dict[str, Any]]:
    return [
        {"marker": i, "name": p.name, "path": str(p.relative_to(workspace.root))}
        for i, p in enumerate(workspace.list_mongodb_log_files(run_id), start=1)
    ]
