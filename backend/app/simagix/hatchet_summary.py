from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.core.run_workspace import RunWorkspace


def load_hatchet_summary(workspace_root: Path, run_id: str) -> dict[str, Any] | None:
    path = RunWorkspace(workspace_root).resolve_hatchet_summary_path(run_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_hatchet_evidence_block(summary: dict[str, Any]) -> str:
    meta = summary.get("metadata", {})
    parts = [
        "You are reviewing tier-1 Hatchet log evidence (MongoDB JSON logs). "
        "Use it alongside mongo-ftdc metrics; cite slow ops, audit highlights, or log examples.\n",
        f"Hatchet analysis: {summary.get('hatchet_name')} (merge={summary.get('merge')})\n",
        f"MongoDB: {meta.get('mongodb_version')} · {meta.get('start')} → {meta.get('end')}\n",
        f"Log lines parsed: {meta.get('log_line_count')}\n",
    ]

    source_files = summary.get("source_files", [])
    if source_files:
        parts.append("\nSource files:\n")
        for item in source_files:
            parts.append(
                f"- marker {item.get('marker')}: {item.get('name')} ({item.get('line_count', '?')} lines)\n"
            )

    parts.append("\nTop slow ops (by avg ms):\n")
    parts.extend(_format_ops(summary.get("top_slow_ops_by_avg_ms", [])[:10]))

    parts.append("\nTop slow ops (by total ms):\n")
    parts.extend(_format_ops(summary.get("top_slow_ops_by_total_ms", [])[:10]))

    collscan = summary.get("collscan_ops", [])
    if collscan:
        parts.append("\nCOLLSCAN / collection scan patterns:\n")
        parts.extend(_format_ops(collscan[:10]))

    audit = summary.get("audit_highlights", [])[:15]
    if audit:
        parts.append("\nAudit highlights:\n")
        for row in audit:
            parts.append(f"- [{row.get('type')}] {row.get('name')}: {row.get('value')}\n")

    drivers = summary.get("observed_drivers", [])[:10]
    if drivers:
        parts.append("\nObserved drivers:\n")
        for row in drivers:
            parts.append(f"- {row.get('driver')} {row.get('version')} (n={row.get('count')})\n")

    examples = summary.get("slow_log_examples", [])[:5]
    if examples:
        parts.append("\nSlow log examples:\n")
        for ex in examples:
            parts.append(
                f"- {ex.get('date')} {ex.get('op')} {ex.get('ns')} {ex.get('milli')}ms marker={ex.get('marker')}\n"
                f"  {ex.get('snippet', '')}\n"
            )

    timeline = summary.get("connection_timeline", [])[:12]
    if timeline:
        parts.append("\nConnection timeline (accepted/ended per minute bucket):\n")
        for row in timeline:
            parts.append(
                f"- {row.get('bucket')}: accepted={row.get('accepted')} ended={row.get('ended')}\n"
            )

    return "".join(parts)


def _format_ops(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        lines.append(
            f"- {row.get('op')} ns={row.get('ns')} avg={row.get('avg_ms')}ms "
            f"count={row.get('count')} total={row.get('total_ms')}ms marker={row.get('marker')}\n"
        )
    return lines or ["- none\n"]
