from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.catalog import count_phase1_attempts, list_phase1_attempts
from backend.app.main import create_app


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
