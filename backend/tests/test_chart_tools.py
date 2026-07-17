"""Chart data helpers: series fetch (tier-2 fallback), CSV shaping, PNG store + serve."""
from __future__ import annotations

import pytest

from backend.app.db.connection import db_conn
from backend.app.simagix.evidence.chart_tools import (
    fetch_series,
    load_chart_png,
    series_to_csv,
    store_chart_png,
)

_RUN = "charttest20260716T000000Z"
_PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngbody"


@pytest.fixture()
def _seed_metric_rows():
    """Insert a small synthetic series into the tier-2 metrics table (ts in ms)."""
    base_ms = 1_780_000_000_000
    with db_conn() as conn:
        for i in range(30):
            conn.execute(
                "INSERT INTO metrics (run_id, name, ts, value) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (_RUN, "cache_used", base_ms + i * 1000, 100.0 + i),
            )
    yield
    with db_conn() as conn:
        conn.execute("DELETE FROM metrics WHERE run_id = %s", (_RUN,))
        conn.execute("DELETE FROM raw_files WHERE run_id = %s", (_RUN,))


def test_fetch_series_metrics_fallback(_seed_metric_rows) -> None:
    series = fetch_series(_RUN, None, ["cache_used"], 1_780_000_000.0, 1_780_000_100.0)
    assert list(series.keys()) == ["cache_used"]
    assert len(series["cache_used"]) == 30
    ts0, value0 = series["cache_used"][0]
    assert ts0 == 1_780_000_000.0
    assert value0 == 100.0


def test_fetch_series_no_data_omits_path() -> None:
    assert fetch_series(_RUN, None, ["nonexistent_metric"], 1.0, 2.0) == {}


def test_series_to_csv_wide_format_with_gaps() -> None:
    series = {
        "b/metric": [[1.0, 10.0], [2.0, 20.0]],
        "a/metric": [[2.0, 5.0], [3.0, 6.0]],
    }
    csv_text = series_to_csv(series)
    lines = csv_text.strip().split("\n")
    assert lines[0] == "ts,a/metric,b/metric"
    # ts=1.0 has no a/metric sample → empty cell; ts=3.0 has no b/metric sample.
    assert lines[1] == "1.000,,10.0"
    assert lines[2] == "2.000,5.0,20.0"
    assert lines[3] == "3.000,6.0,"


def test_store_and_load_chart_png(_seed_metric_rows) -> None:
    chart_id = store_chart_png(_RUN, _PNG)
    assert len(chart_id) == 12
    assert load_chart_png(_RUN, chart_id) == _PNG
    assert load_chart_png(_RUN, "000000000000") is None


def test_chart_endpoint_serves_png(_seed_metric_rows) -> None:
    from fastapi.testclient import TestClient
    from backend.app.main import create_app

    chart_id = store_chart_png(_RUN, _PNG)

    client = TestClient(create_app())
    resp = client.get(f"/simagix/runs/{_RUN}/phase2/charts/{chart_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == _PNG

    missing = client.get(f"/simagix/runs/{_RUN}/phase2/charts/000000000000")
    assert missing.status_code == 404
