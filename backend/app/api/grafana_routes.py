from __future__ import annotations

import subprocess
import urllib.error
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.app.core.run_workspace import get_run_workspace
from backend.app.grafana.links import build_grafana_links
from backend.app.grafana.service import load_run_for_grafana
from backend.app.grafana.stack import GrafanaStackManager

router = APIRouter(prefix="/simagix/runs", tags=["simagix-grafana"])


def _docker_unavailable_detail(raw: str) -> str:
    lowered = raw.lower()
    if "cannot connect to the docker daemon" in lowered or "docker daemon running" in lowered:
        return (
            "Docker is not running. Start Colima (or Docker Desktop), then retry: "
            "colima start --cpu 4 --memory 8"
        )
    return raw


@router.post("/{run_id}/grafana/load")
def load_run_into_grafana(run_id: str) -> dict[str, object]:
    workspace = get_run_workspace()
    try:
        return load_run_for_grafana(workspace.root, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        stderr = getattr(exc, "stderr", None) or ""
        detail = stderr if isinstance(stderr, str) and stderr.strip() else str(exc)
        detail = _docker_unavailable_detail(detail)
        raise HTTPException(status_code=503, detail=f"Grafana stack unavailable: {detail}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc))
        if "timed out" in reason.lower():
            raise HTTPException(
                status_code=504,
                detail=(
                    "FTDC data load timed out. Large diagnostic.data sets can take ~2 minutes. "
                    "Retry after Docker containers finish starting."
                ),
            ) from exc
        raise HTTPException(status_code=502, detail=reason) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{run_id}/grafana/urls")
def get_grafana_urls(run_id: str) -> dict[str, object]:
    workspace = get_run_workspace()
    bundle = workspace.resolve_exports_dir(run_id)
    if not (bundle / "manifest.json").exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    stack = GrafanaStackManager(workspace.root)
    links = build_grafana_links(workspace.root, run_id, bundle)
    return {
        "run_id": run_id,
        "stack": {
            "ftdc_api": stack.is_ftdc_api_up(),
            "grafana": stack.is_grafana_up(),
        },
        "input_path": links.input_path,
        "anomaly_focus_url": links.anomaly_focus_url,
        "all_metrics_url": links.all_metrics_url,
        "anomaly_metrics": links.anomaly_metrics,
        "anomaly_window": links.anomaly_window,
        "time_range_full": links.time_range_full,
        "grafana_base": links.grafana_base,
    }


@router.get("/grafana/status")
def grafana_stack_status() -> dict[str, object]:
    stack = GrafanaStackManager(get_run_workspace().root)
    return {
        "ftdc_api": stack.is_ftdc_api_up(),
        "grafana": stack.is_grafana_up(),
        "grafana_url": stack.settings.grafana_url,
        "ftdc_api_url": stack.settings.ftdc_api_url,
    }
