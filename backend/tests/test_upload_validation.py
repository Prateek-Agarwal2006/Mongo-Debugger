from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.app.api.upload import _is_log_filename
from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.catalog import count_phase1_attempts, list_phase1_attempts
from backend.app.jobs.job_types import JOB_TYPE_HATCHET
from backend.app.main import create_app


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("mongod.log", True),
        ("mongod.log.gz", True),
        ("slow.log.txt", True),
        ("mongod-case.log.2026-06-16T03-22-01", True),
        (".hidden.log", False),
        ("metrics.interim", False),
        ("archive.zip", False),
    ],
)
def test_is_log_filename(name: str, expected: bool) -> None:
    assert _is_log_filename(name) is expected


def test_upload_mongodb_logs_accepts_rotated_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260620T120000Z"
    diag = workspace.upload_diagnostic_dir(run_id)
    diag.mkdir(parents=True)
    (diag / "metrics.interim").write_bytes(b"ftdc")

    monkeypatch.setattr("backend.app.api.upload.get_run_workspace", lambda: workspace)

    client = TestClient(create_app())
    response = client.post(
        f"/simagix/uploads/runs/{run_id}/logs",
        files=[
            ("files", ("mongod.log", b"log-a", "text/plain")),
            ("files", ("mongod.log.2026-06-16T03-22-01", b"log-b", "text/plain")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_type"] == JOB_TYPE_HATCHET
    assert set(body["saved_files"]) == {"mongod.log", "mongod.log.2026-06-16T03-22-01"}
    assert workspace.has_mongodb_log_inputs(run_id)


def test_upload_mongodb_logs_accepts_log_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260620T120002Z"
    diag = workspace.upload_diagnostic_dir(run_id)
    diag.mkdir(parents=True)

    monkeypatch.setattr("backend.app.api.upload.get_run_workspace", lambda: workspace)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mongod-case.log", b"log-a")
        zf.writestr("nested/mongod-case.log.2026-06-16T03-22-01", b"log-b")
    buf.seek(0)

    client = TestClient(create_app())
    response = client.post(
        f"/simagix/uploads/runs/{run_id}/logs",
        files=[("files", ("case-7-logs.zip", buf.getvalue(), "application/zip"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_type"] == JOB_TYPE_HATCHET
    assert set(body["saved_files"]) == {
        "mongod-case.log",
        "mongod-case.log.2026-06-16T03-22-01",
    }


def test_upload_mongodb_logs_rejects_non_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260620T120001Z"
    diag = workspace.upload_diagnostic_dir(run_id)
    diag.mkdir(parents=True)

    monkeypatch.setattr("backend.app.api.upload.get_run_workspace", lambda: workspace)

    client = TestClient(create_app())
    response = client.post(
        f"/simagix/uploads/runs/{run_id}/logs",
        files=[("files", ("metrics.interim", b"ftdc", "application/octet-stream"))],
    )

    assert response.status_code == 400
    assert "Unsupported log file" in response.json()["detail"]


def test_upload_mongodb_logs_rejects_invalid_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260620T120004Z"
    diag = workspace.upload_diagnostic_dir(run_id)
    diag.mkdir(parents=True)

    monkeypatch.setattr("backend.app.api.upload.get_run_workspace", lambda: workspace)

    client = TestClient(create_app())
    response = client.post(
        f"/simagix/uploads/runs/{run_id}/logs",
        files=[("files", ("broken.zip", b"not-a-zip", "application/zip"))],
    )

    assert response.status_code == 400
    assert "Invalid zip archive" in response.json()["detail"]


def test_upload_mongodb_logs_rejects_zip_without_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260620T120003Z"
    diag = workspace.upload_diagnostic_dir(run_id)
    diag.mkdir(parents=True)

    monkeypatch.setattr("backend.app.api.upload.get_run_workspace", lambda: workspace)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metrics.interim", b"not a mongod log")
    buf.seek(0)

    client = TestClient(create_app())
    response = client.post(
        f"/simagix/uploads/runs/{run_id}/logs",
        files=[("files", ("empty.zip", buf.getvalue(), "application/zip"))],
    )

    assert response.status_code == 400
    assert "Archive must contain" in response.json()["detail"]


def test_upload_rejects_invalid_archive_and_removes_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = RunWorkspace(tmp_path)
    monkeypatch.setattr("backend.app.api.upload.get_run_workspace", lambda: workspace)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mongod-case.log", b"not ftdc")
    buf.seek(0)

    client = TestClient(create_app())
    response = client.post(
        "/simagix/uploads",
        files={"file": ("logs.zip", buf.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert list(workspace.uploads_root().glob("upload*")) == []


def test_phase1_attempt_count_ignores_latest_symlink(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260620T120000Z"
    jobs_dir = workspace.phase1_jobs_dir(run_id)
    jobs_dir.mkdir(parents=True)
    job_json = jobs_dir / "job-a.json"
    job_json.write_text(
        '{"job_id":"job-a","run_id":"upload20260620T120000Z","state":"succeeded",'
        '"created_at":1,"updated_at":2,"message":"ok"}',
        encoding="utf-8",
    )
    latest = workspace.uploads_root() / "latest"
    latest.symlink_to(workspace.upload_dir(run_id), target_is_directory=True)

    assert count_phase1_attempts(workspace, run_id) == 1
    assert len(list_phase1_attempts(tmp_path, run_id)) == 1
