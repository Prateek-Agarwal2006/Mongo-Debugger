from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.core.run_workspace import RunWorkspace

LLM_FOLDER_NAMES = frozenset({"mock", "cursor", "gemini"})

_LLM_LABELS = {
    "mock": "Mock",
    "cursor": "Cursor SDK",
    "gemini": "Gemini ADK",
}


def llm_folder_name(provider: str | None) -> str:
    """Map API/provider id to on-disk folder name under phase2/llm/."""
    if not provider:
        raise ValueError("llm provider is required")
    name = provider.strip().lower()
    if name in {"", "default"}:
        raise ValueError("llm provider is required (default is not a folder name)")
    if name == "gemini-adk":
        return "gemini"
    if name in LLM_FOLDER_NAMES:
        return name
    raise ValueError(f"Unknown llm folder: {provider}")


def _workspace(workspace_root: Path) -> RunWorkspace:
    return RunWorkspace(workspace_root)


def phase2_root_dir(workspace_root: Path, run_id: str) -> Path:
    return _workspace(workspace_root).resolve_phase2_dir(run_id)


def llm_session_dir(workspace_root: Path, run_id: str, llm: str) -> Path:
    folder = llm_folder_name(llm) if llm not in LLM_FOLDER_NAMES else llm
    if folder not in LLM_FOLDER_NAMES:
        raise ValueError(f"Unknown llm folder: {llm}")
    return _workspace(workspace_root).llm_session_dir(run_id, folder)


def llm_index_path(workspace_root: Path, run_id: str) -> Path:
    return _workspace(workspace_root).llm_index_path(run_id)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _session_summary(llm_dir: Path, llm: str) -> dict[str, Any]:
    state = _read_json(llm_dir / "iterative_state.json")
    metadata = _read_json(llm_dir / "session_metadata.json")
    has_report = (llm_dir / "latest_report.json").exists()
    status = "not_started"
    last_run_at: float | None = None
    if state:
        status = str(state.get("status", "not_started"))
    if metadata:
        last_run_at = metadata.get("last_run_at")
    return {
        "llm": llm,
        "label": _LLM_LABELS.get(llm, llm),
        "status": status,
        "last_run_at": last_run_at,
        "has_report": has_report,
    }


def list_llm_sessions(workspace_root: Path, run_id: str) -> list[dict[str, Any]]:
    llm_root = phase2_root_dir(workspace_root, run_id) / "llm"
    if not llm_root.is_dir():
        return []
    sessions: list[dict[str, Any]] = []
    for child in sorted(llm_root.iterdir()):
        if not child.is_dir() or child.name not in LLM_FOLDER_NAMES:
            continue
        sessions.append(_session_summary(child, child.name))
    sessions.sort(
        key=lambda item: item.get("last_run_at") or 0,
        reverse=True,
    )
    return sessions


def update_llm_index(workspace_root: Path, run_id: str, llm: str, *, status: str) -> None:
    folder = llm_folder_name(llm) if llm not in LLM_FOLDER_NAMES else llm
    index_path = llm_index_path(workspace_root, run_id)
    entries = list_llm_sessions(workspace_root, run_id)
    by_llm = {entry["llm"]: entry for entry in entries}
    summary = _session_summary(llm_session_dir(workspace_root, run_id, folder), folder)
    summary["status"] = status
    by_llm[folder] = summary
    merged = sorted(by_llm.values(), key=lambda item: item.get("last_run_at") or 0, reverse=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def llm_has_artifacts(workspace_root: Path, run_id: str, llm: str) -> bool:
    session_dir = llm_session_dir(workspace_root, run_id, llm)
    markers = (
        "latest_report.json",
        "investigation.json",
        "tool_trace.json",
        "iterative_state.json",
    )
    return any((session_dir / name).exists() for name in markers)
