from __future__ import annotations

import json

from backend.app.api.grafana_simple import (
    _AnnotationRequest,
    _QueryRequest,
    _QueryTarget,
    _SearchRequest,
    annotations,
    health,
    open_config,
    query,
    run_range,
    search,
)
from backend.app.db.connection import db_conn


def _seed_metric(run_id: str, name: str, ts_ms: float, value: float) -> None:
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO metrics (run_id, name, ts, value) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (run_id, name, ts_ms, value),
        )


def _seed_exec_context(run_id: str) -> None:
    payload = {
        "top_anomaly_windows": [
            {
                "metric": "cpu_user",
                "from": "2026-06-05T10:15:00Z",
                "to": "2026-06-05T10:20:00Z",
            }
        ]
    }
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s::jsonb)"
            " ON CONFLICT (run_id, key) DO UPDATE SET data = EXCLUDED.data",
            (run_id, "executive_context", json.dumps(payload)),
        )


def test_grafana_simple_health_and_config() -> None:
    assert health() == {"status": "ok"}
    cfg = open_config()
    assert "url" in cfg
    assert cfg["anomaly"]["uid"] == "simagix-grafana-anomaly"
    assert cfg["all_metrics"]["uid"] == "simagix-grafana"


def test_grafana_simple_search_runs_and_metrics() -> None:
    run_id = "grafana_test_run"
    _seed_metric(run_id, "cpu_user", 1_780_654_368_000.0, 12.0)
    runs = search(_SearchRequest(target="runs"))
    assert run_id in runs
    metrics = search(_SearchRequest(target="cpu"))
    assert "cpu_user" in metrics


def test_grafana_simple_query_and_annotations() -> None:
    run_id = "grafana_test_run"
    _seed_metric(run_id, "cpu_user", 1_780_654_368_000.0, 12.0)
    _seed_exec_context(run_id)

    series = query(
        _QueryRequest(
            range={
                "from": "2026-06-05T10:00:00.000Z",
                "to": "2026-06-05T11:00:00.000Z",
            },
            targets=[_QueryTarget(target=f"{run_id}/cpu_user")],
        )
    )
    assert series
    assert series[0]["target"] == "cpu_user"
    assert series[0]["datapoints"]

    anns = annotations(_AnnotationRequest(annotation={"query": run_id}))
    assert anns
    assert anns[0]["isRegion"] is True
    assert anns[0]["title"] == "cpu_user"


def test_grafana_simple_run_range_pads_metric_window() -> None:
    run_id = "grafana_range_run"
    _seed_metric(run_id, "cpu_user", 1_780_654_368_000.0, 12.0)
    _seed_metric(run_id, "cpu_user", 1_780_654_728_000.0, 15.0)

    got = run_range(run_id)
    assert got["from"] == 1_780_654_368_000 - 5 * 60 * 1000
    assert got["to"] == 1_780_654_728_000 + 5 * 60 * 1000
    assert got["has_anomalies"] is False
    assert got["anomaly_from"] == got["from"]
    assert got["anomaly_to"] == got["to"]


def test_grafana_simple_run_range_uses_anomaly_windows() -> None:
    run_id = "grafana_anomaly_range_run"
    _seed_metric(run_id, "cpu_user", 1_780_654_000_000.0, 1.0)
    _seed_metric(run_id, "cpu_user", 1_780_655_000_000.0, 2.0)
    _seed_exec_context(run_id)

    got = run_range(run_id)
    assert got["has_anomalies"] is True
    # 10:15Z → 10:20Z on 2026-06-05, ±5 min pad
    assert got["anomaly_from"] == 1_780_654_500_000 - 5 * 60 * 1000
    assert got["anomaly_to"] == 1_780_654_800_000 + 5 * 60 * 1000


def test_grafana_simple_run_range_missing_run() -> None:
    assert run_range("no_such_run_for_grafana_range") == {
        "from": None,
        "to": None,
        "anomaly_from": None,
        "anomaly_to": None,
        "has_anomalies": False,
    }
