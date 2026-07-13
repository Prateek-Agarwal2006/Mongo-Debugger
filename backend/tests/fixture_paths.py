from __future__ import annotations

from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RUN_ID = "phase1test20260609T133314Z"
FAKE_FTDC_METRICS = (
    Path(__file__).resolve().parent / "fixtures/fake_ftdc/metrics.2026-06-10T00-00-00Z-00000"
)


def fixture_workspace() -> RunWorkspace:
    return RunWorkspace(REPO_ROOT)


def fixture_exports_dir() -> Path:
    return fixture_workspace().resolve_exports_dir(FIXTURE_RUN_ID)


def fixture_bundle_exists() -> bool:
    return (fixture_exports_dir() / "manifest.json").is_file()
