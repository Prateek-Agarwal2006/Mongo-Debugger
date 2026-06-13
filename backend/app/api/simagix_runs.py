from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.app.simagix.eval import evaluate_run
from backend.app.simagix.orchestrator import SimagixRCAOrchestrator

router = APIRouter(prefix="/simagix/runs", tags=["simagix-runs"])


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _orchestrator(run_id: str) -> SimagixRCAOrchestrator:
    orchestrator = SimagixRCAOrchestrator(_workspace_root(), run_id)
    if not orchestrator.loader.exists():
        raise HTTPException(status_code=404, detail=f"Simagix run bundle not found: {run_id}")
    return orchestrator


@router.get("")
def list_runs() -> dict[str, object]:
    exports_dir = _workspace_root() / "simagix-workspace/exports/mongo-ftdc"
    if not exports_dir.exists():
        return {"runs": []}
    runs = sorted(
        [
            item.name
            for item in exports_dir.iterdir()
            if item.is_dir() and (item / "manifest.json").exists()
        ],
        reverse=True,
    )
    return {"runs": runs}


@router.get("/{run_id}/context")
def get_tier1_context(run_id: str) -> dict[str, object]:
    return _orchestrator(run_id).get_prompt_context()


@router.get("/{run_id}/tier1")
def get_tier1_bundle(run_id: str) -> dict[str, object]:
    tier1 = _orchestrator(run_id).load_tier1()
    return tier1.model_dump()


@router.get("/{run_id}/tools/metric-window")
def get_metric_window(
    run_id: str,
    metric: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500,
) -> dict[str, object]:
    try:
        return _orchestrator(run_id).get_metric_window(metric, start=start, end=end, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/{run_id}/tools/normalized-series")
def get_normalized_series(
    run_id: str,
    metric: Annotated[list[str], Query(...)],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500,
) -> dict[str, object]:
    try:
        return _orchestrator(run_id).get_normalized_series(metric, start=start, end=end, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/{run_id}/tools/raw-path")
def get_raw_path(
    run_id: str,
    path_contains: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> dict[str, object]:
    try:
        return _orchestrator(run_id).get_raw_path(path_contains, start=start, end=end, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/{run_id}/tools/fallback-metrics")
def list_fallback_metrics(run_id: str, pattern: str | None = None) -> dict[str, object]:
    return {"metrics": _orchestrator(run_id).list_fallback_metrics(pattern)}


@router.get("/{run_id}/budget")
def get_budget(run_id: str) -> dict[str, object]:
    return _orchestrator(run_id).get_budget_status()


@router.get("/{run_id}/phase2/package")
def get_phase2_package(run_id: str) -> dict[str, object]:
    return _orchestrator(run_id).build_phase2_llm_package()


@router.get("/{run_id}/eval")
def evaluate_simagix_run(run_id: str) -> dict[str, object]:
    return evaluate_run(_workspace_root(), run_id)
