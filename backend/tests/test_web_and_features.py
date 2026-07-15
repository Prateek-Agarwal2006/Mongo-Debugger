from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core.run_workspace import RunWorkspace
from backend.app.main import create_app
from backend.app.simagix.anomaly_correlation import build_correlation_package
from backend.app.simagix.llm.service import (
    generate_clarifying_questions_for_run,
    run_investigation,
)
from backend.app.simagix.rca_service import SimagixEvidenceService
from backend.tests.fixture_paths import FAKE_FTDC_METRICS

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RUN_ID = "phase1test20260609T133314Z"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _poll_status_until(client: TestClient, run_id: str, done: set[str], *, timeout_s: float = 60.0) -> dict:
    deadline = time.time() + timeout_s
    body: dict = {}
    while time.time() < deadline:
        resp = client.get(f"/simagix/runs/{run_id}/phase2/status?llm=mock")
        assert resp.status_code == 200
        body = resp.json()
        if body.get("status") in done:
            return body
        time.sleep(0.1)
    raise AssertionError(f"phase2 status never reached {done}: last={body}")


def _complete_mock_rca(client: TestClient, run_id: str) -> dict:
    start = client.post(f"/simagix/runs/{run_id}/phase2/run", json={"llm": "mock"})
    assert start.status_code == 202
    state = _poll_status_until(client, run_id, {"awaiting_clarifications", "failed"})
    assert state["status"] == "awaiting_clarifications", state.get("error")
    qids = [q["id"] for q in state["questions"]["questions"]]
    answers = {qids[0]: "No maintenance during window"} if qids else {}
    clarify = client.post(
        f"/simagix/runs/{run_id}/phase2/clarify?llm=mock",
        json={"answers": answers},
    )
    assert clarify.status_code == 202
    state = _poll_status_until(client, run_id, {"completed", "failed"})
    assert state["status"] == "completed", state.get("error")
    return state


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_docs_page(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_redoc_page(client: TestClient) -> None:
    response = client.get("/redoc")
    assert response.status_code == 200


def test_catalog_lists_runs(client: TestClient) -> None:
    response = client.get("/simagix/catalog")
    assert response.status_code == 200
    assert "runs" in response.json()


def test_catalog_run_workspace_for_fixture(client: TestClient) -> None:
    response = client.get(f"/simagix/catalog/{FIXTURE_RUN_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == FIXTURE_RUN_ID
    assert body["view"] in {"run_workspace", "pipeline"}
    assert body.get("selected_llm") or body.get("pipeline_status")


def test_anomaly_correlation_api(client: TestClient) -> None:
    response = client.get(f"/simagix/runs/{FIXTURE_RUN_ID}/phase2/anomaly-correlation")
    assert response.status_code == 200
    body = response.json()
    assert body["approach"] == "hybrid"
    assert "correlated_clusters" in body


def test_anomaly_correlation_deterministic() -> None:
    orch = SimagixEvidenceService(WORKSPACE_ROOT, FIXTURE_RUN_ID)
    tier1 = orch.load_tier1()
    package = build_correlation_package(tier1.executive_context)
    assert package["deterministic_anomaly_count"] >= 0


def test_investigation_before_clarify() -> None:
    investigation = run_investigation(WORKSPACE_ROOT, FIXTURE_RUN_ID, llm="mock", force_mock=True)
    assert investigation.run_id == FIXTURE_RUN_ID
    assert investigation.findings_reviewed
    assert investigation.tool_calls_made

    inv_path = RunWorkspace(WORKSPACE_ROOT).llm_session_dir(FIXTURE_RUN_ID, "mock") / "investigation.json"
    assert inv_path.exists()

    questions = generate_clarifying_questions_for_run(
        WORKSPACE_ROOT,
        FIXTURE_RUN_ID,
        llm="mock",
        force_mock=True,
        investigation=investigation,
    )
    assert 1 <= len(questions.questions) <= 10


def test_clarifying_questions() -> None:
    investigation = run_investigation(WORKSPACE_ROOT, FIXTURE_RUN_ID, llm="mock", force_mock=True)
    questions = generate_clarifying_questions_for_run(
        WORKSPACE_ROOT,
        FIXTURE_RUN_ID,
        llm="mock",
        force_mock=True,
        investigation=investigation,
    )
    assert questions.run_id == FIXTURE_RUN_ID
    assert 1 <= len(questions.questions) <= 10
    assert all(q.id and q.question and q.rationale for q in questions.questions)


def test_phase2_flow_api(client: TestClient) -> None:
    result = _complete_mock_rca(client, FIXTURE_RUN_ID)
    assert result["status"] == "completed"
    report = client.get(f"/simagix/runs/{FIXTURE_RUN_ID}/phase2/reports/latest?llm=mock")
    assert report.status_code == 200
    assert report.json()["report"]["summary"]


def test_html_report_view(client: TestClient) -> None:
    _complete_mock_rca(client, FIXTURE_RUN_ID)
    response = client.get(
        f"/simagix/runs/{FIXTURE_RUN_ID}/phase2/reports/latest/view?llm=mock"
    )
    assert response.status_code == 200
    assert "Root Cause Analysis" in response.text
    assert "chart.js" not in response.text.lower()


def test_upload_zip_starts_job(client: TestClient, tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metrics.2026-06-10T00-00-00Z-00000", FAKE_FTDC_METRICS.read_bytes())
    buf.seek(0)

    with patch("backend.app.api.upload.JobQueue.enqueue") as mock_enqueue:
        response = client.post(
            "/simagix/uploads",
            files={"file": ("diagnostic.zip", buf.getvalue(), "application/zip")},
        )
    assert response.status_code == 200
    body = response.json()
    assert "job_id" in body
    assert "run_id" in body
    mock_enqueue.assert_called_once()


def test_phase2_report_persists_in_postgres(client: TestClient) -> None:
    from backend.app.simagix.llm.state import load_state

    run_id = FIXTURE_RUN_ID
    _complete_mock_rca(client, run_id)
    payload = load_state(run_id, "mock", "report")
    assert payload is not None
    assert payload["run_id"] == run_id
