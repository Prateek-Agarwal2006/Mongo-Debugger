from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.run_workspace import RunWorkspace, get_run_workspace


def test_exports_dir_points_at_mongo_ftdc_bundle(tmp_path: Path) -> None:
    run_id = "abc123"
    workspace = RunWorkspace(tmp_path)

    assert workspace.exports_dir(run_id) == (
        tmp_path / "simagix-workspace/exports/mongo-ftdc/abc123"
    )


def test_uploads_dir_points_at_diagnostic_upload_root(tmp_path: Path) -> None:
    run_id = "upload20260618T120000Z"
    workspace = RunWorkspace(tmp_path)

    assert workspace.uploads_dir(run_id) == (
        tmp_path / "simagix-workspace/data/uploads/upload20260618T120000Z"
    )


def test_upload_diagnostic_dir(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "r1"
    assert workspace.upload_diagnostic_dir(run_id) == workspace.uploads_dir(run_id) / "diagnostic.data"


def test_phase2_and_llm_session_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "r1"
    assert workspace.phase2_dir(run_id) == tmp_path / "simagix-workspace/runs/r1/phase2"
    assert workspace.llm_session_dir(run_id, "mock") == (
        tmp_path / "simagix-workspace/runs/r1/phase2/llm/mock"
    )
    assert workspace.llm_index_path(run_id) == tmp_path / "simagix-workspace/runs/r1/phase2/llm_index.json"


def test_run_manifest_and_job_status_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "r1"
    job_id = "job-abc"
    assert workspace.run_manifest_path(run_id) == tmp_path / "simagix-workspace/runs/r1/run_manifest.json"
    assert workspace.job_status_path(run_id) == tmp_path / "simagix-workspace/runs/r1/job_status.json"
    assert workspace.job_record_path(job_id) == tmp_path / "simagix-workspace/data/jobs/job-abc.json"
    assert workspace.job_queue_pending_path(job_id) == (
        tmp_path / "simagix-workspace/data/job_queue/pending/job-abc.json"
    )


def test_tooling_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    assert workspace.pipeline_script() == tmp_path / "simagix-workspace/scripts/run-mongo-ftdc-pipeline.sh"
    assert workspace.grafana_compose_file() == tmp_path / "simagix-workspace/docker/grafana-compose.yaml"


def test_list_run_ids_requires_manifest(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    assert workspace.list_run_ids() == []

    bundle = workspace.exports_dir("good")
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    workspace.exports_dir("empty").mkdir(parents=True)

    assert workspace.list_run_ids() == ["good"]


def test_get_run_workspace_uses_data_root_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.core.config import get_settings

    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        workspace = get_run_workspace()
        assert workspace.root == tmp_path.resolve()
        assert workspace.exports_dir("x") == tmp_path / "simagix-workspace/exports/mongo-ftdc/x"
    finally:
        get_settings.cache_clear()
