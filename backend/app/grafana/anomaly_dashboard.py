from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _graph_panel(panel_id: int, title: str, targets: list[str], y: int, *, w: int = 12, h: int = 5) -> dict[str, Any]:
    return {
        "datasource": "ftdc",
        "gridPos": {"h": h, "w": w, "x": 0 if panel_id % 2 == 0 else w, "y": y},
        "id": panel_id,
        "targets": [{"refId": chr(65 + index), "target": target, "type": "timeserie"} for index, target in enumerate(targets)],
        "title": title,
        "type": "graph",
        "lines": True,
        "linewidth": 1,
        "nullPointMode": "null",
        "xaxis": {"mode": "time", "show": True},
        "yaxes": [
            {"format": "short", "logBase": 1, "show": True},
            {"format": "short", "logBase": 1, "show": False},
        ],
    }


def build_anomaly_focus_dashboard() -> dict[str, Any]:
    panels: list[dict[str, Any]] = [
        {
            "datasource": "ftdc",
            "gridPos": {"h": 6, "w": 24, "x": 0, "y": 0},
            "id": 1,
            "targets": [{"refId": "A", "target": "assessment", "type": "table"}],
            "title": "Assessment (worst metrics first)",
            "type": "table",
        },
        _graph_panel(2, "WiredTiger Tickets (read / write)", ["ticket_avail_read", "ticket_avail_write"], 6),
        _graph_panel(3, "Replication Lags", ["replication_lags"], 6, w=12),
        _graph_panel(4, "WiredTiger Cache", ["wt_cache_used", "wt_cache_dirty"], 11),
        _graph_panel(5, "CPU", ["cpu_user", "cpu_idle", "cpu_iowait"], 11, w=12),
        _graph_panel(6, "Opcounters", ["ops_query", "ops_insert", "ops_update", "ops_delete"], 16, w=24),
        _graph_panel(7, "Scans & Targeting", ["scan_objects", "scan_keys"], 21),
        _graph_panel(8, "Write Conflicts", ["write_conflicts/s"], 21, w=12),
        _graph_panel(9, "Connections", ["conns_current", "conns_active"], 26),
        _graph_panel(10, "Global Lock Queue", ["q_queued_read", "q_queued_write"], 26, w=12),
    ]
    panels[2]["gridPos"]["x"] = 12

    return {
        "annotations": {"list": []},
        "editable": True,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "panels": panels,
        "schemaVersion": 16,
        "style": "dark",
        "tags": ["ftdc", "anomaly"],
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
        "timezone": "browser",
        "title": "MongoDB FTDC — Anomaly Focus",
        "uid": "simagix-grafana-anomaly",
        "version": 1,
    }


def write_anomaly_dashboard(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_anomaly_focus_dashboard(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    from backend.app.core.run_workspace import RunWorkspace, repo_root

    out = RunWorkspace(repo_root()).grafana_anomaly_dashboard_path()
    write_anomaly_dashboard(out)
    print(f"Wrote {out}")
