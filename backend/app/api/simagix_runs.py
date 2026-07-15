from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.run_workspace import get_run_workspace
from backend.app.simagix.eval import evaluate_run
from backend.app.simagix.evidence.loader import list_run_ids as _pg_list_run_ids
from backend.app.simagix.rca_service import SimagixEvidenceService

router = APIRouter(prefix="/simagix/runs", tags=["simagix-runs"])


def _evidence_service(run_id: str) -> SimagixEvidenceService:
    workspace = get_run_workspace()
    service = SimagixEvidenceService(workspace.root, run_id)
    if not service.loader.exists():
        raise HTTPException(status_code=404, detail=f"Simagix run bundle not found: {run_id}")
    return service


@router.get("")
def list_runs() -> dict[str, object]:
    return {"runs": _pg_list_run_ids()}


@router.get("/{run_id}/context")
def get_tier1_context(run_id: str) -> dict[str, object]:
    return _evidence_service(run_id).get_prompt_context()


@router.get("/{run_id}/tier1")
def get_tier1_bundle(run_id: str) -> dict[str, object]:
    tier1 = _evidence_service(run_id).load_tier1()
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
        return _evidence_service(run_id).get_metric_window(metric, start=start, end=end, limit=limit)
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
        return _evidence_service(run_id).get_normalized_series(metric, start=start, end=end, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/{run_id}/tools/fallback-metrics")
def list_fallback_metrics(run_id: str, pattern: str | None = None) -> dict[str, object]:
    return {"metrics": _evidence_service(run_id).list_fallback_metrics(pattern)}


@router.get("/{run_id}/budget")
def get_budget(run_id: str) -> dict[str, object]:
    return _evidence_service(run_id).get_budget_status()


@router.get("/{run_id}/phase2/package")
def get_phase2_package(run_id: str) -> dict[str, object]:
    return _evidence_service(run_id).build_phase2_llm_package()


@router.get("/{run_id}/eval")
def evaluate_simagix_run(run_id: str) -> dict[str, object]:
    return evaluate_run(get_run_workspace().root, run_id)
