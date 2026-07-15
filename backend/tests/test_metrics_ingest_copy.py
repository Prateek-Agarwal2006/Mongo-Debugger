"""Metrics ingest uses replace + COPY (not row-wise upsert)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from backend.app.db.connection import db_conn
from backend.app.jobs.ingest import _ingest_time_series

_RUN = "test_metrics_copy_run"


def test_ingest_time_series_replace_via_copy(tmp_path: Path) -> None:
    bundle = tmp_path / "mongo-ftdc"
    norm = bundle / "normalized"
    norm.mkdir(parents=True)
    series = {
        "target": "cpu_idle",
        "datapoints": [[0.9, 1_700_000_000_000], [0.8, 1_700_000_060_000]],
    }
    with gzip.open(norm / "time_series.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(series) + "\n")

    with db_conn() as conn:
        conn.execute("DELETE FROM metrics WHERE run_id = %s", (_RUN,))
        _ingest_time_series(conn, _RUN, bundle)
        rows = conn.execute(
            "SELECT name, ts, value FROM metrics WHERE run_id = %s ORDER BY ts",
            (_RUN,),
        ).fetchall()
        # Second ingest replaces (still 2 rows, not 4).
        _ingest_time_series(conn, _RUN, bundle)
        n = conn.execute(
            "SELECT count(*) FROM metrics WHERE run_id = %s", (_RUN,)
        ).fetchone()[0]
        conn.execute("DELETE FROM metrics WHERE run_id = %s", (_RUN,))

    assert len(rows) == 2
    assert rows[0][0] == "cpu_idle"
    assert n == 2
