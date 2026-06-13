from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.simagix.schemas import TimeRange


def _parse_ts(value: int | float) -> datetime:
    if value > 1_000_000_000_000:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _in_window(ts: datetime, start: datetime | None, end: datetime | None) -> bool:
    if start and ts < start:
        return False
    return not (end and ts > end)


class SimagixFallbackTools:
    """Read-only fallback retrieval tools for tier_2/tier_3 bundle files."""

    def __init__(self, bundle_dir: Path) -> None:
        self.bundle_dir = bundle_dir.resolve()

    def get_metric_window(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        index = self._load_fallback_index()
        entry = self._pick_index_entry(index, metric)
        if entry is None:
            return {"metric": metric, "points": [], "source_file": None, "tier": None}

        source_file = entry.get("source_file")
        source = entry.get("source")
        if source == "replication_lags":
            points = self._slice_replication_lag(metric, start, end, limit)
        elif source == "disk_stats":
            points = self._slice_disk_metric(metric, start, end, limit)
        else:
            points = self._slice_time_series(metric, start, end, limit)

        return {
            "metric": metric,
            "source_file": source_file,
            "tier": entry.get("tier"),
            "related_finding": entry.get("related_finding"),
            "window": {"from": start, "to": end},
            "points": points,
            "point_count": len(points),
        }

    def get_normalized_series(
        self,
        metrics: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        return {
            metric: self.get_metric_window(metric, start=start, end=end, limit=limit)
            for metric in metrics
        }

    def get_raw_path(
        self,
        path_contains: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        raw_file = self.bundle_dir / "raw/raw_metric_values.jsonl.gz"
        if not raw_file.exists():
            return {
                "path_contains": path_contains,
                "matches": [],
                "error": "tier_3 raw export not present in bundle",
            }

        matches: list[dict[str, Any]] = []
        with gzip.open(raw_file, "rt", encoding="utf-8") as handle:
            for line in handle:
                if len(matches) >= limit:
                    break
                record = json.loads(line)
                path = record.get("path", "")
                if path_contains.lower() not in path.lower():
                    continue
                values = record.get("values", [])
                matches.append(
                    {
                        "source_file": record.get("source_file"),
                        "block_index": record.get("block_index"),
                        "path": path,
                        "value_count": len(values),
                        "values": values[: min(len(values), 50)],
                    }
                )
        return {
            "path_contains": path_contains,
            "window": {"from": start, "to": end},
            "matches": matches,
            "match_count": len(matches),
        }

    def list_fallback_metrics(self, pattern: str | None = None) -> list[str]:
        index = self._load_fallback_index()
        names = sorted({entry.get("metric", "") for entry in index if entry.get("metric")})
        if not pattern:
            return names
        needle = pattern.lower()
        return [name for name in names if needle in name.lower()]

    def _load_fallback_index(self) -> list[dict[str, Any]]:
        path = self.bundle_dir / "llm/fallback_retrieval_index.json"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _pick_index_entry(self, index: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
        metric_lower = metric.lower()
        for entry in index:
            if entry.get("metric", "").lower() == metric_lower:
                return entry
        for entry in index:
            if metric_lower in entry.get("metric", "").lower():
                return entry
        return None

    def _slice_time_series(
        self,
        metric: str,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[list[float | int]]:
        path = self.bundle_dir / "normalized/time_series.jsonl.gz"
        if not path.exists():
            return []
        target = metric.lower()
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                name = record.get("target", "").lower()
                if name != target and target not in name:
                    continue
                points: list[list[float | int]] = []
                for value, ts in record.get("datapoints", []):
                    ts_dt = _parse_ts(ts)
                    if not _in_window(ts_dt, start, end):
                        continue
                    points.append([value, ts])
                    if len(points) >= limit:
                        break
                return points
        return []

    def _slice_replication_lag(
        self,
        metric: str,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[list[float | int]]:
        path = self.bundle_dir / "normalized/replication_lags.json"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        host_key = metric.replace("replication_lag.", "").replace("repl_lag_", "")
        series = None
        for key, value in payload.items():
            if key == host_key or host_key in key or metric.endswith(key):
                series = value
                break
        if series is None and payload:
            series = next(iter(payload.values()))
        if not series:
            return []
        points: list[list[float | int]] = []
        for value, ts in series.get("datapoints", []):
            ts_dt = _parse_ts(ts)
            if not _in_window(ts_dt, start, end):
                continue
            points.append([value, ts])
            if len(points) >= limit:
                break
        return points

    def _slice_disk_metric(
        self,
        metric: str,
        start: datetime | None,
        end: datetime | None,
        limit: int,
    ) -> list[list[float | int]]:
        path = self.bundle_dir / "normalized/disk_stats.json"
        if not path.exists():
            return []
        parts = metric.split(".")
        if len(parts) < 3:
            return []
        disk = parts[1]
        field = parts[2]
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        disk_stats = payload.get(disk)
        if not disk_stats:
            return []
        field_map = {
            "iops": "IOPS",
            "io_in_progress": "IOInProgress",
            "io_queued_ms": "IOQueuedMS",
            "read_time_ms": "ReadTimeMS",
            "write_time_ms": "WriteTimeMS",
            "utilization": "Utilization",
        }
        key = field_map.get(field, field)
        series = disk_stats.get(key) or disk_stats.get(key.lower())
        if not series:
            return []
        datapoints = series.get("datapoints") or series.get("DataPoints") or []
        points: list[list[float | int]] = []
        for value, ts in datapoints:
            ts_dt = _parse_ts(ts)
            if not _in_window(ts_dt, start, end):
                continue
            points.append([value, ts])
            if len(points) >= limit:
                break
        return points
