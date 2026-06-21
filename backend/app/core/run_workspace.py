from __future__ import annotations

from pathlib import Path

_SIMAGIX = "simagix-workspace"


def repo_root() -> Path:
    """Repository root (parent of backend/)."""
    return Path(__file__).resolve().parents[3]


class RunWorkspace:
    """Run-scoped paths — Option A: one tree per upload under simagix-workspace/uploads/{run_id}/."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def simagix_root(self) -> Path:
        return self.root / _SIMAGIX

    # --- Upload tree (canonical) ---

    def uploads_root(self) -> Path:
        return self.simagix_root / "uploads"

    def upload_dir(self, run_id: str) -> Path:
        return self.uploads_root() / run_id

    def uploads_dir(self, run_id: str) -> Path:
        """Alias for upload_dir (backward-compatible name)."""
        return self.upload_dir(run_id)

    def upload_diagnostic_dir(self, run_id: str) -> Path:
        return self.upload_dir(run_id) / "raw" / "diagnostic.data"

    def profiler_dir(self, run_id: str) -> Path:
        return self.upload_dir(run_id) / "raw" / "profiler"

    def phase1_dir(self, run_id: str) -> Path:
        return self.upload_dir(run_id) / "phase1"

    def phase1_jobs_dir(self, run_id: str) -> Path:
        return self.phase1_dir(run_id) / "jobs"

    def job_record_path(self, run_id: str, job_id: str) -> Path:
        return self.phase1_jobs_dir(run_id) / f"{job_id}.json"

    def phase1_queue_root(self, run_id: str) -> Path:
        return self.phase1_dir(run_id) / "queue"

    def job_queue_pending_dir(self, run_id: str) -> Path:
        return self.phase1_queue_root(run_id) / "pending"

    def job_queue_processing_dir(self, run_id: str) -> Path:
        return self.phase1_queue_root(run_id) / "processing"

    def job_queue_pending_path(self, run_id: str, job_id: str) -> Path:
        return self.job_queue_pending_dir(run_id) / f"{job_id}.json"

    def job_queue_processing_path(self, run_id: str, job_id: str) -> Path:
        return self.job_queue_processing_dir(run_id) / f"{job_id}.json"

    def exports_dir(self, run_id: str) -> Path:
        """Phase 1 evidence bundle (mongo-ftdc export)."""
        return self.phase1_dir(run_id) / "evidence"

    def exports_root(self) -> Path:
        """Legacy name — prefer uploads_root + exports_dir(run_id)."""
        return self.simagix_root / "exports/mongo-ftdc"

    def run_manifest_path(self, run_id: str) -> Path:
        return self.phase1_dir(run_id) / "run_manifest.json"

    def job_status_path(self, run_id: str) -> Path:
        return self.phase1_dir(run_id) / "job_status.json"

    def phase2_dir(self, run_id: str) -> Path:
        return self.upload_dir(run_id) / "phase2"

    def phase2_llm_root(self, run_id: str) -> Path:
        return self.phase2_dir(run_id) / "llm"

    def llm_session_dir(self, run_id: str, llm_folder: str) -> Path:
        return self.phase2_llm_root(run_id) / llm_folder

    def llm_index_path(self, run_id: str) -> Path:
        return self.phase2_dir(run_id) / "llm_index.json"

    def runs_root(self) -> Path:
        """Legacy runs root (phase2 only in old layout)."""
        return self.simagix_root / "runs"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root() / run_id

    # --- Legacy paths (pre–Option A layout) ---

    def legacy_upload_diagnostic_dir(self, run_id: str) -> Path:
        return self.simagix_root / "data/uploads" / run_id / "diagnostic.data"

    def legacy_exports_dir(self, run_id: str) -> Path:
        return self.exports_root() / run_id

    def legacy_jobs_root(self) -> Path:
        return self.simagix_root / "data/jobs"

    def legacy_job_record_path(self, job_id: str) -> Path:
        return self.legacy_jobs_root() / f"{job_id}.json"

    def legacy_job_queue_pending_dir(self) -> Path:
        return self.simagix_root / "data/job_queue/pending"

    def legacy_job_queue_processing_dir(self) -> Path:
        return self.simagix_root / "data/job_queue/processing"

    def legacy_job_queue_pending_path(self, job_id: str) -> Path:
        return self.legacy_job_queue_pending_dir() / f"{job_id}.json"

    def legacy_job_queue_processing_path(self, job_id: str) -> Path:
        return self.legacy_job_queue_processing_dir() / f"{job_id}.json"

    def legacy_run_manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run_manifest.json"

    def legacy_job_status_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "job_status.json"

    def legacy_phase2_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "phase2"

    # --- Resolve: prefer canonical, fall back to legacy on disk ---

    def resolve_upload_diagnostic_dir(self, run_id: str) -> Path:
        if self.upload_diagnostic_dir(run_id).is_dir():
            return self.upload_diagnostic_dir(run_id)
        legacy = self.legacy_upload_diagnostic_dir(run_id)
        if legacy.is_dir():
            return legacy
        return self.upload_diagnostic_dir(run_id)

    def resolve_exports_dir(self, run_id: str) -> Path:
        if (self.exports_dir(run_id) / "manifest.json").exists():
            return self.exports_dir(run_id)
        legacy = self.legacy_exports_dir(run_id)
        if (legacy / "manifest.json").exists():
            return legacy
        return self.exports_dir(run_id)

    def resolve_phase2_dir(self, run_id: str) -> Path:
        if self.phase2_dir(run_id).exists():
            return self.phase2_dir(run_id)
        legacy = self.legacy_phase2_dir(run_id)
        if legacy.exists():
            return legacy
        return self.phase2_dir(run_id)

    def resolve_run_manifest_path(self, run_id: str) -> Path:
        if self.run_manifest_path(run_id).exists():
            return self.run_manifest_path(run_id)
        legacy = self.legacy_run_manifest_path(run_id)
        if legacy.exists():
            return legacy
        return self.run_manifest_path(run_id)

    def upload_exists(self, run_id: str) -> bool:
        return self.resolve_upload_diagnostic_dir(run_id).is_dir()

    def iter_upload_run_dirs(self) -> list[Path]:
        """Run folders under uploads/ — skips `latest` symlink and non-run entries."""
        uploads = self.uploads_root()
        if not uploads.is_dir():
            return []
        run_dirs: list[Path] = []
        for item in sorted(uploads.iterdir()):
            if not item.is_dir() or item.name == "latest" or item.is_symlink():
                continue
            run_dirs.append(item)
        return run_dirs

    def find_job_record_path(self, job_id: str) -> Path | None:
        for run_dir in self.iter_upload_run_dirs():
            path = run_dir / "phase1" / "jobs" / f"{job_id}.json"
            if path.is_file():
                return path
        legacy = self.legacy_job_record_path(job_id)
        if legacy.is_file():
            return legacy
        return None

    def iter_phase1_queue_pending_paths(self) -> list[Path]:
        paths: list[Path] = []
        for run_dir in self.iter_upload_run_dirs():
            pending = run_dir / "phase1" / "queue" / "pending"
            if pending.is_dir():
                paths.extend(sorted(pending.glob("*.json")))
        legacy_pending = self.legacy_job_queue_pending_dir()
        if legacy_pending.is_dir():
            paths.extend(sorted(legacy_pending.glob("*.json")))
        return paths

    def iter_phase1_queue_processing_paths(self) -> list[Path]:
        paths: list[Path] = []
        for run_dir in self.iter_upload_run_dirs():
            processing = run_dir / "phase1" / "queue" / "processing"
            if processing.is_dir():
                paths.extend(sorted(processing.glob("*.json")))
        legacy_processing = self.legacy_job_queue_processing_dir()
        if legacy_processing.is_dir():
            paths.extend(sorted(legacy_processing.glob("*.json")))
        return paths

    def pipeline_script(self) -> Path:
        return self.simagix_root / "scripts/run-mongo-ftdc-pipeline.sh"

    def grafana_compose_file(self) -> Path:
        return self.simagix_root / "docker/grafana-compose.yaml"

    def grafana_anomaly_dashboard_path(self) -> Path:
        return self.simagix_root / "grafana/dashboards/anomaly-focus.json"

    def list_run_ids(self) -> list[str]:
        run_ids: set[str] = set()
        for item in self.iter_upload_run_dirs():
            if (item / "phase1" / "evidence" / "manifest.json").is_file():
                run_ids.add(item.name)
        legacy_exports = self.exports_root()
        if legacy_exports.is_dir():
            for item in legacy_exports.iterdir():
                if item.is_dir() and (item / "manifest.json").is_file():
                    run_ids.add(item.name)
        return sorted(run_ids, reverse=True)


def get_run_workspace() -> RunWorkspace:
    from backend.app.core.config import get_settings

    settings = get_settings()
    root = settings.data_root if settings.data_root is not None else repo_root()
    return RunWorkspace(root)
