"""Chart data + storage helpers for Phase 2 reports.

Series fetching (tier-3 raw FTDC with tier-2 metrics fallback) and PNG
storage in the raw_files chunk store (kind="charts") so charts survive pod
restarts and are servable from any API replica.

Chart *rendering* is not done here: LLM-authored plotting code executes in a
Daytona sandbox (see sandbox_plot.py) — never inside the pod.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from backend.app.db.connection import db_conn
from backend.app.db.raw_files import store_raw_bytes
from backend.app.simagix.evidence.ftdc_tools import FtdcTools

_CHARTS_KIND = "charts"
MAX_PATHS_PER_CHART = 4


def chart_filename(chart_id: str) -> str:
    return f"{chart_id}.png"


def _fallback_metric_series(run_id: str, name: str, start_ts: float, end_ts: float) -> list[list[float]]:
    """Tier-2 metrics table fallback — ts stored in epoch ms, returned as [ts_s, value]."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT ts, value FROM metrics"
            " WHERE run_id = %s AND name = %s AND ts >= %s AND ts <= %s"
            " ORDER BY ts LIMIT 5000",
            (run_id, name, start_ts * 1000, end_ts * 1000),
        ).fetchall()
    return [[row[0] / 1000.0, row[1]] for row in rows]


def fetch_series(
    run_id: str,
    workspace_root: Path | None,
    paths: list[str],
    start_ts: float,
    end_ts: float,
) -> dict[str, list[list[float]]]:
    """Return {path: [[ts, value], ...]} for each path with data in the window.

    Tries tier-3 raw FTDC series first (get_raw_window); any path with no raw
    data falls back to the tier-2 metrics table by exact name. Paths with no
    data in either tier are omitted from the result.
    """
    ftdc = FtdcTools(run_id, workspace_root=workspace_root)
    raw = ftdc.get_raw_window(paths, start_ts, end_ts)
    series: dict[str, list[list[float]]] = dict(raw.get("series") or {})

    for path in paths:
        if not series.get(path):
            fallback = _fallback_metric_series(run_id, path, start_ts, end_ts)
            if fallback:
                series[path] = fallback

    return {p: pts for p, pts in series.items() if pts}


def series_to_csv(series: dict[str, list[list[float]]]) -> str:
    """Flatten series into a wide CSV: ts column + one column per metric path.

    Rows are the sorted union of timestamps; a path with no sample at a given
    ts gets an empty cell (pandas reads it as NaN, matplotlib skips it).
    """
    paths = sorted(series.keys())
    by_ts: dict[float, dict[str, float]] = {}
    for path, points in series.items():
        for ts, value in points:
            by_ts.setdefault(ts, {})[path] = value

    lines = ["ts," + ",".join(paths)]
    for ts in sorted(by_ts):
        row = by_ts[ts]
        cells = [f"{ts:.3f}"] + [str(row[p]) if p in row else "" for p in paths]
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def store_chart_png(run_id: str, png: bytes) -> str:
    """Store PNG bytes in the chunk store; return the new chart_id."""
    chart_id = uuid.uuid4().hex[:12]
    with db_conn() as conn:
        store_raw_bytes(conn, run_id, _CHARTS_KIND, chart_filename(chart_id), png)
    return chart_id


def load_chart_png(run_id: str, chart_id: str) -> bytes | None:
    from backend.app.db.raw_files import read_raw_file_bytes

    with db_conn() as conn:
        return read_raw_file_bytes(conn, run_id, _CHARTS_KIND, chart_filename(chart_id))
