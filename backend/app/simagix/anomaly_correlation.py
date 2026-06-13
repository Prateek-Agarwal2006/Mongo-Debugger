from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.simagix.schemas import AnomalyWindow, ExecutiveContext


def _overlap_seconds(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0.0
    return (end - start).total_seconds()


def correlate_anomalies_deterministic(context: ExecutiveContext) -> list[dict[str, Any]]:
    windows = context.top_anomaly_windows
    if not windows:
        return []

    clusters: list[dict[str, Any]] = []
    used: set[int] = set()

    for index, window in enumerate(windows):
        if index in used:
            continue
        group = [window]
        used.add(index)
        for other_index, other in enumerate(windows):
            if other_index in used:
                continue
            overlap = _overlap_seconds(window.from_, window.to, other.from_, other.to)
            if overlap > 0 or abs((other.from_ - window.from_).total_seconds()) < 600:
                group.append(other)
                used.add(other_index)

        metrics = [item.metric for item in group]
        peak = max(item.peak for item in group)
        clusters.append(
            {
                "cluster_id": f"cluster-{index + 1}",
                "metrics": metrics,
                "severity": max(item.severity for item in group),
                "peak_value": peak,
                "from": min(item.from_ for item in group).isoformat(),
                "to": max(item.to for item in group).isoformat(),
                "observation": _observation_for_cluster(metrics, group),
                "source": "deterministic",
            }
        )

    return clusters


def _observation_for_cluster(metrics: list[str], group: list[AnomalyWindow]) -> str:
    metric_set = set(metrics)
    if any("repl_lag" in m for m in metric_set):
        return (
            "Replication lag anomalies overlap with resource pressure signals; "
            "secondary apply throughput may be the bottleneck."
        )
    if any("ticket" in m for m in metric_set):
        return (
            "WiredTiger ticket metrics degraded in the same window as cache/CPU signals; "
            "concurrent operations likely exhausted the ticket pool."
        )
    if any("write_conflict" in m for m in metric_set):
        return "Write conflict spikes suggest concurrent update contention on hot documents."
    if any("cpu" in m for m in metric_set):
        return "CPU saturation window correlates with query or replication pressure."
    primary = group[0].metric
    return f"Correlated degradation across {len(metrics)} metrics centered on {primary}."


def build_correlation_package(context: ExecutiveContext) -> dict[str, Any]:
    clusters = correlate_anomalies_deterministic(context)
    return {
        "approach": "hybrid",
        "deterministic_anomaly_count": context.anomaly_event_count,
        "finding_count": len(context.findings),
        "correlated_clusters": clusters,
        "llm_narrative": None,
        "instruction": (
            "Deterministic mongo-ftdc anomalies are authoritative. "
            "LLM correlation narrative may be added when CURSOR_API_KEY is configured."
        ),
    }
