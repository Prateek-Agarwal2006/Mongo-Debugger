from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings, get_settings

# Grafana slug derived from dashboard title "MongoDB FTDC — Anomaly Focus"
ANOMALY_DASHBOARD_SLUG = "mongodb-ftdc-e28094-anomaly-focus"


@dataclass
class GrafanaViewLinks:
    run_id: str
    grafana_base: str
    ftdc_api_base: str
    input_path: str
    all_metrics_url: str
    anomaly_focus_url: str
    anomaly_window: dict[str, str]
    anomaly_metrics: list[str]
    time_range_full: dict[str, str]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_grafana_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _load_manifest(bundle_dir: Path) -> dict[str, Any]:
    path = bundle_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_anomaly_windows(bundle_dir: Path) -> list[dict[str, Any]]:
    path = bundle_dir / "llm/executive_context.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("top_anomaly_windows", []))


def _resolve_input_path(workspace_root: Path, run_id: str, manifest: dict[str, Any]) -> Path:
    run_manifest = workspace_root / "simagix-workspace/runs" / run_id / "run_manifest.json"
    if run_manifest.exists():
        run_meta = json.loads(run_manifest.read_text(encoding="utf-8"))
        rel = run_meta.get("input", "")
        if rel:
            candidate = workspace_root / rel
            if candidate.exists():
                return candidate.resolve()

    raw = manifest.get("input", "")
    if raw.startswith("/workspace/"):
        raw = raw.removeprefix("/workspace/")
    candidate = workspace_root / raw
    if candidate.exists():
        return candidate.resolve()

    default = workspace_root / "tmp/diagnostic.data"
    if default.exists():
        return default.resolve()
    raise FileNotFoundError(f"No diagnostic.data path found for run {run_id}")


def _anomaly_time_window(
    windows: list[dict[str, Any]],
    *,
    padding_minutes: int,
    manifest: dict[str, Any],
) -> tuple[datetime, datetime, list[str]]:
    if not windows:
        tr = manifest.get("time_range", {})
        start = _parse_iso(tr["from"])
        end = _parse_iso(tr["to"])
        return start, end, []

    metrics: list[str] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    for window in windows:
        metrics.append(str(window.get("metric", "")))
        from_key = "from" if "from" in window else "from_"
        starts.append(_parse_iso(window[from_key]))
        ends.append(_parse_iso(window["to"]))

    start = min(starts) - timedelta(minutes=padding_minutes)
    end = max(ends) + timedelta(minutes=padding_minutes)
    return start, end, [m for m in metrics if m]


def build_grafana_links(
    workspace_root: Path,
    run_id: str,
    bundle_dir: Path,
    settings: Settings | None = None,
) -> GrafanaViewLinks:
    settings = settings or get_settings()
    manifest = _load_manifest(bundle_dir)
    windows = _load_anomaly_windows(bundle_dir)
    input_path = _resolve_input_path(workspace_root, run_id, manifest)

    full_tr = manifest.get("time_range", {})
    full_from = _parse_iso(full_tr["from"])
    full_to = _parse_iso(full_tr["to"])

    anomaly_from, anomaly_to, anomaly_metrics = _anomaly_time_window(
        windows,
        padding_minutes=settings.graph_padding_minutes,
        manifest=manifest,
    )

    grafana_base = settings.grafana_url.rstrip("/")
    all_url = (
        f"{grafana_base}/d/simagix-grafana/mongodb-mongo-ftdc"
        f"?from={_to_grafana_ms(full_from)}&to={_to_grafana_ms(full_to)}&kiosk=tv"
    )
    anomaly_url = (
        f"{grafana_base}/d/simagix-grafana-anomaly/{ANOMALY_DASHBOARD_SLUG}"
        f"?from={_to_grafana_ms(anomaly_from)}&to={_to_grafana_ms(anomaly_to)}&kiosk=tv"
    )

    return GrafanaViewLinks(
        run_id=run_id,
        grafana_base=grafana_base,
        ftdc_api_base=settings.ftdc_api_url.rstrip("/"),
        input_path=str(input_path),
        all_metrics_url=all_url,
        anomaly_focus_url=anomaly_url,
        anomaly_window={
            "from": anomaly_from.isoformat(),
            "to": anomaly_to.isoformat(),
        },
        anomaly_metrics=anomaly_metrics,
        time_range_full={
            "from": full_from.isoformat(),
            "to": full_to.isoformat(),
        },
    )
