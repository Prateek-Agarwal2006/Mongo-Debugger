from __future__ import annotations

import subprocess
import urllib.error
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.grafana.links import build_grafana_links
from backend.app.grafana.stack import GrafanaStackManager


def _bundle_dir(workspace_root: Path, run_id: str) -> Path:
    return RunWorkspace(workspace_root).resolve_exports_dir(run_id)


def load_run_for_grafana(workspace_root: Path, run_id: str) -> dict[str, object]:
    bundle = _bundle_dir(workspace_root, run_id)
    if not (bundle / "manifest.json").exists():
        raise FileNotFoundError(f"Run not found: {run_id}")

    stack = GrafanaStackManager(workspace_root)
    status = stack.ensure_running()

    links = build_grafana_links(workspace_root, run_id, bundle)
    host_path = Path(links.input_path)
    container_path = stack.container_path_for_host(host_path)
    load_result = stack.load_run_data(container_path)

    return {
        "run_id": run_id,
        "stack": status,
        "input_path": links.input_path,
        "container_path": container_path,
        "load": load_result,
        "anomaly_focus_url": links.anomaly_focus_url,
        "all_metrics_url": links.all_metrics_url,
        "anomaly_metrics": links.anomaly_metrics,
        "anomaly_window": links.anomaly_window,
        "time_range_full": links.time_range_full,
    }


def warm_grafana_for_run(workspace_root: Path, run_id: str) -> bool:
    """Best-effort FTDC load into Grafana after pipeline export. Non-fatal on failure."""
    try:
        load_run_for_grafana(workspace_root, run_id)
        return True
    except (
        FileNotFoundError,
        RuntimeError,
        subprocess.CalledProcessError,
        urllib.error.URLError,
        OSError,
    ):
        return False
