from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def profiler_dir(workspace_root: Path, run_id: str) -> Path:
    return workspace_root / "simagix-workspace/data/uploads" / run_id / "profiler"


def save_profiler_data(workspace_root: Path, run_id: str, payload: list[dict[str, Any]]) -> Path:
    dest = profiler_dir(workspace_root, run_id)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "system.profile.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_profiler_data(workspace_root: Path, run_id: str, *, limit: int = 50) -> dict[str, Any]:
    path = profiler_dir(workspace_root, run_id) / "system.profile.json"
    if not path.exists():
        return {"available": False, "samples": [], "path": str(path)}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return {"available": True, "samples": [], "path": str(path), "error": "Expected JSON array"}
    return {
        "available": True,
        "path": str(path),
        "sample_count": len(raw),
        "samples": raw[:limit],
    }
