from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.simagix.anomaly_correlation import build_correlation_package
from backend.app.simagix.llm.service import (
    generate_clarifying_questions_for_run,
    run_investigation,
)
from backend.app.simagix.orchestrator import SimagixRCAOrchestrator
from backend.app.simagix.profiler import load_profiler_data, save_profiler_data

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RUN_ID = "phase1test20260609T133314Z"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _complete_mock_rca(client: TestClient, run_id: str) -> dict:
    start = client.post(f"/simagix/runs/{run_id}/phase2/run", json={"force_mock": True})
    assert start.status_code == 200
    body = start.json()
    qids = [q["id"] for q in body["clarifying_questions"]["questions"]]
    answers = {qids[0]: "No maintenance during window"} if qids else {}
    clarify = client.post(
        f"/simagix/runs/{run_id}/phase2/clarify?force_mock=true",
        json={"answers": answers},
    )
    assert clarify.status_code == 200
    return clarify.json()


def test_home_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "FTDC Analyzer" in response.text


def test_runs_page(client: TestClient) -> None:
    response = client.get("/runs")
    assert response.status_code == 200


def test_run_detail_page(client: TestClient) -> None:
    response = client.get(f"/runs/{FIXTURE_RUN_ID}")
    assert response.status_code == 200
    assert FIXTURE_RUN_ID in response.text
    assert "Run RCA" in response.text
    assert "live stream" not in response.text.lower()
    assert "/analyze" not in response.text
    assert 'id="tool-trace-panel"' in response.text
    assert "Agent Tool Activity" in response.text
    assert "/static/js/rca.js" in response.text


def test_anomaly_correlation_api(client: TestClient) -> None:
    response = client.get(f"/simagix/runs/{FIXTURE_RUN_ID}/phase2/anomaly-correlation")
    assert response.status_code == 200
    body = response.json()
    assert body["approach"] == "hybrid"
    assert "correlated_clusters" in body


def test_anomaly_correlation_deterministic() -> None:
    orch = SimagixRCAOrchestrator(WORKSPACE_ROOT, FIXTURE_RUN_ID)
    tier1 = orch.load_tier1()
    package = build_correlation_package(tier1.executive_context)
    assert package["deterministic_anomaly_count"] >= 0


def test_investigation_before_clarify() -> None:
    investigation = run_investigation(WORKSPACE_ROOT, FIXTURE_RUN_ID, force_mock=True)
    assert investigation.run_id == FIXTURE_RUN_ID
    assert investigation.findings_reviewed
    assert investigation.tool_calls_made

    inv_path = WORKSPACE_ROOT / "simagix-workspace/runs" / FIXTURE_RUN_ID / "phase2/investigation.json"
    assert inv_path.exists()

    questions = generate_clarifying_questions_for_run(
        WORKSPACE_ROOT,
        FIXTURE_RUN_ID,
        force_mock=True,
        investigation=investigation,
    )
    assert 1 <= len(questions.questions) <= 10


def test_clarifying_questions() -> None:
    investigation = run_investigation(WORKSPACE_ROOT, FIXTURE_RUN_ID, force_mock=True)
    questions = generate_clarifying_questions_for_run(
        WORKSPACE_ROOT,
        FIXTURE_RUN_ID,
        force_mock=True,
        investigation=investigation,
    )
    assert questions.run_id == FIXTURE_RUN_ID
    assert 1 <= len(questions.questions) <= 10
    assert all(q.id and q.question and q.rationale for q in questions.questions)


def test_phase2_flow_api(client: TestClient) -> None:
    result = _complete_mock_rca(client, FIXTURE_RUN_ID)
    assert result["status"] == "completed"
    assert result.get("report", {}).get("summary")


def test_profiler_upload_and_fetch(client: TestClient) -> None:
    samples = [{"op": "query", "millis": 120, "ns": "test.orders"}]
    upload = client.post(f"/simagix/runs/{FIXTURE_RUN_ID}/phase2/profiler", json=samples)
    assert upload.status_code == 200
    fetch = client.get(f"/simagix/runs/{FIXTURE_RUN_ID}/phase2/profiler")
    assert fetch.status_code == 200
    assert fetch.json()["available"] is True


def test_profiler_module() -> None:
    save_profiler_data(WORKSPACE_ROOT, "test-profiler-run", [{"op": "update"}])
    data = load_profiler_data(WORKSPACE_ROOT, "test-profiler-run")
    assert data["available"] is True
    assert data["sample_count"] == 1


def test_html_report_view(client: TestClient) -> None:
    _complete_mock_rca(client, FIXTURE_RUN_ID)
    response = client.get(f"/simagix/runs/{FIXTURE_RUN_ID}/phase2/reports/latest/view")
    assert response.status_code == 200
    assert "Root Cause Analysis" in response.text
    assert "chart.js" not in response.text.lower()


def test_upload_zip_starts_job(client: TestClient, tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metrics.2026-06-10T00-00-00Z-00000", b"fake-ftdc-content")
    buf.seek(0)

    with patch("backend.app.api.upload.PipelineJobRunner.start") as mock_start:
        response = client.post(
            "/simagix/uploads",
            files={"file": ("diagnostic.zip", buf.getvalue(), "application/zip")},
        )
    assert response.status_code == 200
    body = response.json()
    assert "job_id" in body
    assert "run_id" in body
    mock_start.assert_called_once()


def test_phase2_report_persists_on_disk(client: TestClient) -> None:
    run_id = FIXTURE_RUN_ID
    _complete_mock_rca(client, run_id)
    report_path = WORKSPACE_ROOT / "simagix-workspace/runs" / run_id / "phase2/latest_report.json"
    assert report_path.exists()
