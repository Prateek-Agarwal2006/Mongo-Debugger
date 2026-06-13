from __future__ import annotations

from pathlib import Path

from backend.app.grafana.links import ANOMALY_DASHBOARD_SLUG, build_grafana_links

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RUN_ID = "phase1test20260609T133314Z"


def test_build_grafana_links() -> None:
    bundle = WORKSPACE_ROOT / "simagix-workspace/exports/mongo-ftdc" / FIXTURE_RUN_ID
    if not (bundle / "manifest.json").exists():
        return

    links = build_grafana_links(WORKSPACE_ROOT, FIXTURE_RUN_ID, bundle)
    assert links.run_id == FIXTURE_RUN_ID
    assert "simagix-grafana-anomaly" in links.anomaly_focus_url
    assert ANOMALY_DASHBOARD_SLUG in links.anomaly_focus_url
    assert "simagix-grafana/mongodb-mongo-ftdc" in links.all_metrics_url
    assert links.anomaly_focus_url != links.all_metrics_url or "from=" in links.anomaly_focus_url


def test_grafana_urls_api() -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    bundle = WORKSPACE_ROOT / "simagix-workspace/exports/mongo-ftdc" / FIXTURE_RUN_ID
    if not (bundle / "manifest.json").exists():
        return

    client = TestClient(create_app())
    resp = client.get(f"/simagix/runs/{FIXTURE_RUN_ID}/grafana/urls")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == FIXTURE_RUN_ID
    assert "anomaly_focus_url" in body
    assert "all_metrics_url" in body
