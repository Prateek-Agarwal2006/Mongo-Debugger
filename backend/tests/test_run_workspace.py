from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.run_workspace import RunWorkspace, get_run_workspace


def test_exports_dir_points_at_phase1_evidence(tmp_path: Path) -> None:
    run_id = "abc123"
    workspace = RunWorkspace(tmp_path)

    assert workspace.exports_dir(run_id) == (
        tmp_path / "simagix-workspace/uploads/abc123/phase1/evidence"
    )


def test_uploads_dir_points_at_upload_tree_root(tmp_path: Path) -> None:
    run_id = "upload20260618T120000Z"
    workspace = RunWorkspace(tmp_path)

    assert workspace.uploads_dir(run_id) == (
        tmp_path / "simagix-workspace/uploads/upload20260618T120000Z"
    )


def test_upload_diagnostic_dir(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "r1"
    assert workspace.upload_diagnostic_dir(run_id) == (
        tmp_path / "simagix-workspace/uploads/r1/raw/diagnostic.data"
    )


def test_phase2_and_llm_session_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "r1"
    assert workspace.phase2_dir(run_id) == tmp_path / "simagix-workspace/uploads/r1/phase2"
    assert workspace.llm_session_dir(run_id, "mock") == (
        tmp_path / "simagix-workspace/uploads/r1/phase2/llm/mock"
    )
    assert workspace.llm_index_path(run_id) == (
        tmp_path / "simagix-workspace/uploads/r1/phase2/llm_index.json"
    )


def test_run_manifest_and_job_status_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "r1"
    job_id = "job-abc"
    assert workspace.run_manifest_path(run_id) == (
        tmp_path / "simagix-workspace/uploads/r1/phase1/run_manifest.json"
    )
    assert workspace.job_status_path(run_id) == (
        tmp_path / "simagix-workspace/uploads/r1/phase1/job_status.json"
    )
    assert workspace.job_record_path(run_id, job_id) == (
        tmp_path / "simagix-workspace/uploads/r1/phase1/jobs/job-abc.json"
    )
    assert workspace.job_queue_pending_path(run_id, job_id) == (
        tmp_path / "simagix-workspace/uploads/r1/phase1/queue/pending/job-abc.json"
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


def test_resolve_legacy_exports_and_uploads(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "legacy-run"
    legacy_bundle = workspace.legacy_exports_dir(run_id)
    legacy_bundle.mkdir(parents=True)
    (legacy_bundle / "manifest.json").write_text("{}", encoding="utf-8")
    legacy_upload = workspace.legacy_upload_diagnostic_dir(run_id)
    legacy_upload.mkdir(parents=True)

    assert workspace.resolve_exports_dir(run_id) == legacy_bundle
    assert workspace.resolve_upload_diagnostic_dir(run_id) == legacy_upload


def test_get_run_workspace_uses_data_root_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.core.config import get_settings

    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        workspace = get_run_workspace()
        assert workspace.root == tmp_path.resolve()
        assert workspace.exports_dir("x") == tmp_path / "simagix-workspace/uploads/x/phase1/evidence"
    finally:
        get_settings.cache_clear()
