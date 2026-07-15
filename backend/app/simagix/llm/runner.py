from __future__ import annotations

"""Async execution of the two long-running phase 2 stages.

POST handlers validate synchronously (missing bundle, hatchet not ready — same
errors as before), write a running status to phase2_state, submit the LLM work
to a small in-process thread pool, and return immediately.  Progress and results
are read from Postgres by GET /phase2/status and the report endpoints, so any
orchestrator pod can serve them.  A failure in the background thread writes
status=failed with the error text — nothing is lost to a dropped connection.

Status lifecycle:
    not_started -> running_investigation -> awaiting_clarifications
                -> running_rca -> completed | failed
"""

import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from backend.app.simagix.evidence.hatchet_tools import assert_hatchet_ready_for_phase2
from backend.app.simagix.llm.service import (
    load_iterative_state,
    normalize_llm_provider_choice,
    resolve_llm_folder,
    resolve_run_llm_provider,
    save_iterative_state,
    start_phase2_run,
    submit_clarifications_and_run,
)
from backend.app.simagix.llm.session import phase2_session_store
from backend.app.simagix.output_schema import ClarifyingAnswers

RUNNING_STATUSES = frozenset({"running_investigation", "running_rca"})

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="phase2")


def _mark_failed(workspace_root: Path, run_id: str, llm: str, exc: Exception) -> None:
    session = phase2_session_store.get_or_create(run_id, workspace_root, llm=llm)
    state = load_iterative_state(session) or {}
    state.update({
        "status": "failed",
        "llm": llm,
        "error": str(exc) or exc.__class__.__name__,
        "error_type": exc.__class__.__name__,
    })
    save_iterative_state(session, state)


def _validate_ready(workspace_root: Path, run_id: str, llm: str) -> None:
    """Raise the same sync errors the blocking endpoints raised (404/409 mapping in API)."""
    session = phase2_session_store.get_or_create(run_id, workspace_root, llm=llm)
    if not session.evidence.loader.exists():
        raise FileNotFoundError(f"Simagix run bundle not found: {run_id}")
    assert_hatchet_ready_for_phase2(workspace_root, run_id)


def start_phase2_run_async(
    workspace_root: Path,
    run_id: str,
    *,
    force_mock: bool = False,
    llm_provider: str | None = None,
    llm: str | None = None,
    enabled_mcp_ids: list[str] | None = None,
) -> dict[str, Any]:
    folder = resolve_llm_folder(llm=llm, llm_provider=llm_provider, force_mock=force_mock)
    _validate_ready(workspace_root, run_id, folder)

    session = phase2_session_store.get_or_create(run_id, workspace_root, llm=folder)
    state = load_iterative_state(session) or {}
    if state.get("status") in RUNNING_STATUSES:
        return {"run_id": run_id, "llm": folder, "status": state["status"], "already_running": True}

    provider_choice = resolve_run_llm_provider(
        llm_provider=llm_provider, force_mock=force_mock
    ) or folder
    save_iterative_state(session, {
        "status": "running_investigation",
        "llm": folder,
        "llm_provider": normalize_llm_provider_choice(provider_choice),
    })

    def _task() -> None:
        try:
            start_phase2_run(
                workspace_root,
                run_id,
                force_mock=force_mock,
                llm_provider=llm_provider,
                llm=folder,
                enabled_mcp_ids=enabled_mcp_ids,
            )
        except Exception as exc:
            traceback.print_exc()
            _mark_failed(workspace_root, run_id, folder, exc)

    _EXECUTOR.submit(_task)
    return {"run_id": run_id, "llm": folder, "status": "running_investigation"}


def submit_clarifications_async(
    workspace_root: Path,
    run_id: str,
    answers: ClarifyingAnswers,
    *,
    force_mock: bool = False,
    llm_provider: str | None = None,
    llm: str | None = None,
    enabled_mcp_ids: list[str] | None = None,
) -> dict[str, Any]:
    folder = resolve_llm_folder(llm=llm, llm_provider=llm_provider, force_mock=force_mock)
    _validate_ready(workspace_root, run_id, folder)

    session = phase2_session_store.get_or_create(run_id, workspace_root, llm=folder)
    state = load_iterative_state(session) or {}
    if state.get("status") in RUNNING_STATUSES:
        return {"run_id": run_id, "llm": folder, "status": state["status"], "already_running": True}

    state.update({"status": "running_rca", "llm": folder, "answers": answers.answers})
    state.pop("error", None)
    state.pop("error_type", None)
    save_iterative_state(session, state)

    def _task() -> None:
        try:
            submit_clarifications_and_run(
                workspace_root,
                run_id,
                answers,
                force_mock=force_mock,
                llm_provider=llm_provider,
                llm=folder,
                enabled_mcp_ids=enabled_mcp_ids,
            )
        except Exception as exc:
            traceback.print_exc()
            _mark_failed(workspace_root, run_id, folder, exc)

    _EXECUTOR.submit(_task)
    return {"run_id": run_id, "llm": folder, "status": "running_rca"}


def shutdown_executor(wait: bool = False) -> None:
    _EXECUTOR.shutdown(wait=wait)
