"""Catalog JSON + Phase 1 RCA gate (SPA bootstrap)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.jobs.catalog import phase1_progress_label
from backend.app.jobs.store import JobState, JobStatus
from backend.app.main import create_app
from backend.tests.fixture_paths import FIXTURE_RUN_ID


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_phase1_progress_label_distinguishes_ingest() -> None:
    assert phase1_progress_label("processing", "Running mongo-ftdc pipeline") == "Decoding"
    assert (
        phase1_progress_label("processing", "Ingesting decoded data into Postgres…")
        == "Loading metrics"
    )
    assert phase1_progress_label("finished", "Pipeline complete") == "Ready"
    assert phase1_progress_label("failed", "Ingest failed") == "Failed"


def test_catalog_run_gates_pipeline_while_job_running(client: TestClient) -> None:
    running = JobStatus(
        job_id="j-running",
        run_id=FIXTURE_RUN_ID,
        state=JobState.RUNNING,
        message="Ingesting decoded data into Postgres…",
    )
    with patch("backend.app.api.catalog.latest_job_for_run", return_value=running):
        with patch("backend.app.api.catalog.EvidenceLoader") as loader:
            loader.return_value.exists.return_value = True
            resp = client.get(f"/simagix/catalog/{FIXTURE_RUN_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["view"] == "pipeline"
    assert body["phase1_label"] == "Loading metrics"


def test_catalog_run_opens_workspace_when_job_succeeded(client: TestClient) -> None:
    done = JobStatus(
        job_id="j-ok",
        run_id=FIXTURE_RUN_ID,
        state=JobState.SUCCEEDED,
        message="Pipeline complete; evidence ready",
    )
    with patch("backend.app.api.catalog.latest_job_for_run", return_value=done):
        with patch("backend.app.api.catalog.EvidenceLoader") as loader:
            loader.return_value.exists.return_value = True
            resp = client.get(f"/simagix/catalog/{FIXTURE_RUN_ID}")
    assert resp.status_code == 200
    assert resp.json()["view"] == "run_workspace"


def test_catalog_run_opens_workspace_for_fixture_without_job(client: TestClient) -> None:
    with patch("backend.app.api.catalog.latest_job_for_run", return_value=None):
        with patch("backend.app.api.catalog.EvidenceLoader") as loader:
            loader.return_value.exists.return_value = True
            resp = client.get(f"/simagix/catalog/{FIXTURE_RUN_ID}")
    assert resp.status_code == 200
    assert resp.json()["view"] == "run_workspace"
