from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.db.connection import db_conn
from backend.app.db.raw_files import reassemble_raw_file


class FtdcTools:
    """Tier-2/3 FTDC metric retrieval from Postgres metrics table."""

    def __init__(self, run_id: str, workspace_root: Path | None = None) -> None:
        self.run_id = run_id
        self._workspace_root = workspace_root

    def get_metric_window(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        start_ms = start.timestamp() * 1000 if start else None
        end_ms = end.timestamp() * 1000 if end else None
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT ts, value FROM metrics"
                " WHERE run_id = %s AND name = %s"
                " AND (%s::double precision IS NULL OR ts >= %s)"
                " AND (%s::double precision IS NULL OR ts <= %s)"
                " ORDER BY ts LIMIT %s",
                (self.run_id, metric, start_ms, start_ms, end_ms, end_ms, limit),
            ).fetchall()
        return {
            "metric": metric,
            "source_file": None,
            "tier": "metrics_table",
            "window": {"from": start, "to": end},
            "points": [[row[1], row[0]] for row in rows],
            "point_count": len(rows),
        }

    def get_normalized_series(
        self,
        metrics: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        return {
            m: self.get_metric_window(m, start=start, end=end, limit=limit)
            for m in metrics
        }

    # ── Tier-3 raw tools ─────────────────────────────────────────────────────

    def list_raw_paths(self, pattern: str | None = None) -> dict[str, Any]:
        """Return the prefix map (no pattern) or matching paths from catalog (with pattern).

        Call with no args first to see the top-level taxonomy (~30 prefixes).
        Then supply a prefix or substring to narrow down to exact path names.
        """
        with db_conn() as conn:
            if pattern is None:
                row = conn.execute(
                    "SELECT data FROM evidence WHERE run_id=%s AND key='raw_path_prefix_map'",
                    (self.run_id,),
                ).fetchone()
                if row is None:
                    return {"error": "raw path catalog not yet built — pipeline must complete first"}
                return row[0]

            row = conn.execute(
                "SELECT data FROM evidence WHERE run_id=%s AND key='raw_path_catalog'",
                (self.run_id,),
            ).fetchone()
            if row is None:
                return {"paths": [], "error": "raw path catalog not yet built"}
            needle = pattern.lower()
            matches = [p for p in row[0].get("paths", []) if needle in p.lower()]
            return {"pattern": pattern, "paths": matches, "count": len(matches)}

    def get_raw_window(
        self,
        paths: list[str],
        start_ts: float,
        end_ts: float,
    ) -> dict[str, Any]:
        """Return per-second time series for the named FTDC paths in [start_ts, end_ts].

        start_ts / end_ts are epoch seconds (float).  Uses raw_file_index to pick
        only the files that overlap the window — no full-table scans.
        """
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT filename FROM raw_file_index"
                " WHERE run_id=%s AND kind='ftdc'"
                " AND start_ts <= %s AND end_ts >= %s"
                " ORDER BY filename",
                (self.run_id, end_ts, start_ts),
            ).fetchall()

        if not rows:
            return {
                "series": {},
                "coverage_gaps": [],
                "files_processed": 0,
                "note": "no FTDC files overlap the requested window",
            }

        with tempfile.TemporaryDirectory(prefix="ftdc-window-") as tmp:
            tmp_path = Path(tmp)
            file_paths: list[Path] = []
            with db_conn() as conn:
                for (fname,) in rows:
                    dest = tmp_path / fname
                    reassemble_raw_file(conn, self.run_id, "ftdc", fname, dest)
                    file_paths.append(dest)

            binary = shutil.which("ftdc-slice") or (
                str(self._workspace_root / "simagix-workspace/repos/mongo-ftdc/ftdc-slice")
                if self._workspace_root else "ftdc-slice"
            )
            cmd = [
                binary, "--mode", "window",
                "--paths", ",".join(paths),
                "--start", str(start_ts),
                "--end", str(end_ts),
                *[str(p) for p in file_paths],
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if not result.stdout.strip():
            return {
                "series": {},
                "coverage_gaps": [],
                "files_processed": 0,
                "error": result.stderr.strip() or "ftdc-slice produced no output",
            }
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"series": {}, "error": "invalid JSON from ftdc-slice", "raw": result.stdout[:500]}

    def list_fallback_metrics(self, pattern: str | None = None) -> list[str]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT name FROM metrics WHERE run_id = %s ORDER BY name",
                (self.run_id,),
            ).fetchall()
        names = [row[0] for row in rows]
        if pattern:
            needle = pattern.lower()
            names = [n for n in names if needle in n.lower()]
        return names


def unique_metrics_from_index(index: list[dict[str, Any]]) -> list[str]:
    """Preserved for callers that use the standalone function from old fallback_tools."""
    return sorted({entry.get("metric", "") for entry in index if entry.get("metric")})
