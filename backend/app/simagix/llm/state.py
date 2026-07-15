from __future__ import annotations

import json
import time
from typing import Any

from backend.app.db.connection import db_conn

LLM_FOLDER_NAMES = frozenset({"mock", "cursor", "gemini"})

_LLM_LABELS = {
    "mock": "Mock",
    "cursor": "Cursor SDK",
    "gemini": "Gemini ADK",
}

ATTACHMENT_KEY_PREFIX = "attachment:"


def llm_folder_name(provider: str | None) -> str:
    """Map API/provider id to the canonical llm slot name (mock/cursor/gemini)."""
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


def load_state(run_id: str, llm: str, key: str) -> Any | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM phase2_state WHERE run_id = %s AND llm = %s AND key = %s",
            (run_id, llm, key),
        ).fetchone()
        return row[0] if row else None


def save_state(run_id: str, llm: str, key: str, data: Any) -> None:
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO phase2_state (run_id, llm, key, data, updated_at)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (run_id, llm, key)"
            " DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at",
            (run_id, llm, key, json.dumps(data), time.time()),
        )


def delete_state(run_id: str, llm: str, key: str | None = None) -> None:
    with db_conn() as conn:
        if key is None:
            conn.execute(
                "DELETE FROM phase2_state WHERE run_id = %s AND llm = %s",
                (run_id, llm),
            )
        else:
            conn.execute(
                "DELETE FROM phase2_state WHERE run_id = %s AND llm = %s AND key = %s",
                (run_id, llm, key),
            )


def llm_has_artifacts(run_id: str, llm: str) -> bool:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM phase2_state WHERE run_id = %s AND llm = %s"
            " AND key IN ('report', 'investigation', 'tool_trace', 'iterative_state')"
            " LIMIT 1",
            (run_id, llm),
        ).fetchone()
        return row is not None


def list_llm_sessions(run_id: str) -> list[dict[str, Any]]:
    """Session summaries per llm slot, derived from state rows (replaces llm_index.json)."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT llm, key, data, updated_at FROM phase2_state"
            " WHERE run_id = %s AND key IN ('iterative_state', 'metadata', 'report')",
            (run_id,),
        ).fetchall()

    by_llm: dict[str, dict[str, Any]] = {}
    for llm, key, data, _updated_at in rows:
        slot = by_llm.setdefault(llm, {})
        slot[key] = data

    sessions: list[dict[str, Any]] = []
    for llm in sorted(by_llm):
        if llm not in LLM_FOLDER_NAMES:
            continue
        slot = by_llm[llm]
        state = slot.get("iterative_state")
        metadata = slot.get("metadata")
        sessions.append({
            "llm": llm,
            "label": _LLM_LABELS.get(llm, llm),
            "status": str(state.get("status", "not_started")) if state else "not_started",
            "last_run_at": metadata.get("last_run_at") if metadata else None,
            "has_report": "report" in slot,
        })
    sessions.sort(key=lambda item: item.get("last_run_at") or 0, reverse=True)
    return sessions


def list_attachments(run_id: str, llm: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT key, data FROM phase2_state"
            " WHERE run_id = %s AND llm = %s AND key LIKE %s",
            (run_id, llm, f"{ATTACHMENT_KEY_PREFIX}%"),
        ).fetchall()
    return [row[1] for row in rows]
