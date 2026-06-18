from __future__ import annotations

from pathlib import Path

_SIMAGIX = "simagix-workspace"


def repo_root() -> Path:
    """Repository root (parent of backend/)."""
    return Path(__file__).resolve().parents[3]


class RunWorkspace:
    """Adapter between Run-scoped domain paths and filesystem layout under a configurable root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def simagix_root(self) -> Path:
        return self.root / _SIMAGIX

    def exports_root(self) -> Path:
        return self.simagix_root / "exports/mongo-ftdc"

    def exports_dir(self, run_id: str) -> Path:
        return self.exports_root() / run_id

    def uploads_root(self) -> Path:
        return self.simagix_root / "data/uploads"

    def uploads_dir(self, run_id: str) -> Path:
        return self.uploads_root() / run_id

    def upload_diagnostic_dir(self, run_id: str) -> Path:
        return self.uploads_dir(run_id) / "diagnostic.data"

    def profiler_dir(self, run_id: str) -> Path:
        return self.uploads_dir(run_id) / "profiler"

    def runs_root(self) -> Path:
        return self.simagix_root / "runs"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root() / run_id

    def run_manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run_manifest.json"

    def job_status_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "job_status.json"

    def phase2_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "phase2"

    def phase2_llm_root(self, run_id: str) -> Path:
        return self.phase2_dir(run_id) / "llm"

    def llm_session_dir(self, run_id: str, llm_folder: str) -> Path:
        return self.phase2_llm_root(run_id) / llm_folder

    def llm_index_path(self, run_id: str) -> Path:
        return self.phase2_dir(run_id) / "llm_index.json"

    def pipeline_script(self) -> Path:
        return self.simagix_root / "scripts/run-mongo-ftdc-pipeline.sh"

    def grafana_compose_file(self) -> Path:
        return self.simagix_root / "docker/grafana-compose.yaml"

    def grafana_anomaly_dashboard_path(self) -> Path:
        return self.simagix_root / "grafana/dashboards/anomaly-focus.json"

    def list_run_ids(self) -> list[str]:
        exports_dir = self.exports_root()
        if not exports_dir.exists():
            return []
        return sorted(
            [
                item.name
                for item in exports_dir.iterdir()
                if item.is_dir() and (item / "manifest.json").exists()
            ],
            reverse=True,
        )


def get_run_workspace() -> RunWorkspace:
    from backend.app.core.config import get_settings

    settings = get_settings()
    root = settings.data_root if settings.data_root is not None else repo_root()
    return RunWorkspace(root)
