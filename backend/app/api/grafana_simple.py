"""Grafana SimpleJSON datasource served from PG metrics + evidence tables.

Configure the datasource URL in Grafana as: http://<host>/grafana/simple

Dashboard setup:
  1. Add a template variable `run_id` — type "Custom Query", query `runs`,
     datasource this file. Grafana calls /search with target="runs" and gets
     the list of all ingested run_ids.
  2. In each panel, set metric to  $run_id/ss.opcounters.insert  — Grafana
     substitutes $run_id before sending to /query. The target arrives as
     upload20260618T120000Z/ss.opcounters.insert.
  3. For anomaly annotations, add a Grafana annotation with query = $run_id
     pointing at this datasource.  Grafana substitutes $run_id and the
     /annotations endpoint returns the anomaly windows for that run.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.core.config import get_settings
from backend.app.db.connection import db_conn

router = APIRouter(prefix="/grafana/simple", tags=["grafana-simple"])

_SEARCH_LIMIT = 500
_QUERY_LIMIT = 5_000
_ANOMALY_PADDING_MINUTES = 5
_RANGE_PADDING_MS = _ANOMALY_PADDING_MINUTES * 60 * 1000
_ANOMALY_UID = "simagix-grafana-anomaly"
_ANOMALY_SLUG = "mongodb-ftdc-e28094-anomaly-focus"
_ALL_METRICS_UID = "simagix-grafana"
_ALL_METRICS_SLUG = "mongodb-ftdc-analytics"


class _SearchRequest(BaseModel):
    target: str = ""


class _QueryTarget(BaseModel):
    target: str = ""
    type: str = "timeseries"


class _QueryRequest(BaseModel):
    range: dict = {}
    targets: list[_QueryTarget] = []
    intervalMs: int = 1000
    maxDataPoints: int = _QUERY_LIMIT


class _AnnotationRequest(BaseModel):
    range: dict = {}
    annotation: dict = {}


def _iso_to_ms(s: str) -> float:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except Exception:
        return 0.0


def _dt_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


@router.get("/")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config")
def open_config() -> dict:
    """UI helper: base URL + anomaly / all-metrics dashboard deep-link ids."""
    settings = get_settings()
    return {
        "url": settings.grafana_url.rstrip("/"),
        "anomaly": {"uid": _ANOMALY_UID, "slug": _ANOMALY_SLUG},
        "all_metrics": {"uid": _ALL_METRICS_UID, "slug": _ALL_METRICS_SLUG},
    }


def _metric_range_ms(run_id: str) -> tuple[int, int] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM metrics WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    return int(row[0]), int(row[1])


def _anomaly_window_ms(run_id: str) -> tuple[int, int] | None:
    """Union of top_anomaly_windows ± padding, or None if missing."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM evidence WHERE run_id = %s AND key = 'executive_context'",
            (run_id,),
        ).fetchone()
    if row is None or not isinstance(row[0], dict):
        return None
    windows = row[0].get("top_anomaly_windows") or []
    starts: list[datetime] = []
    ends: list[datetime] = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        try:
            from_key = "from" if "from" in window else "from_"
            starts.append(datetime.fromisoformat(str(window[from_key]).replace("Z", "+00:00")))
            ends.append(datetime.fromisoformat(str(window["to"]).replace("Z", "+00:00")))
        except (KeyError, ValueError):
            continue
    if not starts:
        return None
    pad = timedelta(minutes=_ANOMALY_PADDING_MINUTES)
    return _dt_to_ms(min(starts) - pad), _dt_to_ms(max(ends) + pad)


@router.get("/runs/{run_id}/range")
def run_range(run_id: str) -> dict[str, int | bool | None]:
    """Full capture window + optional anomaly-focus window for Grafana deep links.

    FTDC timestamps are historical. Grafana ``now-6h`` shows empty panels unless
    ``from``/``to`` are set. Anomaly View uses the anomaly window when present.
    """
    full = _metric_range_ms(run_id)
    if full is None:
        return {
            "from": None,
            "to": None,
            "anomaly_from": None,
            "anomaly_to": None,
            "has_anomalies": False,
        }
    from_ms = full[0] - _RANGE_PADDING_MS
    to_ms = full[1] + _RANGE_PADDING_MS
    anomaly = _anomaly_window_ms(run_id)
    if anomaly is None:
        return {
            "from": from_ms,
            "to": to_ms,
            "anomaly_from": from_ms,
            "anomaly_to": to_ms,
            "has_anomalies": False,
        }
    return {
        "from": from_ms,
        "to": to_ms,
        "anomaly_from": anomaly[0],
        "anomaly_to": anomaly[1],
        "has_anomalies": True,
    }


@router.post("/search")
def search(req: _SearchRequest) -> list[str]:
    target = req.target.strip()

    with db_conn() as conn:
        if target.lower() == "runs":
            # Dashboard variable: return all run_ids that have ingested metrics.
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM metrics ORDER BY run_id DESC LIMIT %s",
                (_SEARCH_LIMIT,),
            ).fetchall()
            return [row[0] for row in rows]

        # Metric name selector for panel editor: return distinct metric names.
        if target:
            rows = conn.execute(
                "SELECT DISTINCT name FROM metrics"
                " WHERE name ILIKE %s ORDER BY name LIMIT %s",
                (f"%{target}%", _SEARCH_LIMIT),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT name FROM metrics ORDER BY name LIMIT %s",
                (_SEARCH_LIMIT,),
            ).fetchall()
    return [row[0] for row in rows]


@router.post("/query")
def query(req: _QueryRequest) -> list[dict]:
    """Return timeseries datapoints.

    Target format: <run_id>/<metric_name>
    Grafana expands the $run_id template variable before sending, so the
    target arrives as e.g. upload20260618T120000Z/ss.opcounters.insert.
    """
    time_range = req.range or {}
    from_ms = _iso_to_ms(str(time_range.get("from", "")))
    to_ms = _iso_to_ms(str(time_range.get("to", "")))
    limit = min(req.maxDataPoints or _QUERY_LIMIT, _QUERY_LIMIT)

    results = []
    for t in req.targets:
        full_target = t.target.strip()
        if "/" not in full_target:
            continue
        run_id, _, metric_name = full_target.partition("/")
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT ts, value FROM metrics"
                " WHERE run_id = %s AND name = %s AND ts >= %s AND ts <= %s"
                " ORDER BY ts LIMIT %s",
                (run_id, metric_name, from_ms, to_ms, limit),
            ).fetchall()
        results.append({
            "target": metric_name,
            "datapoints": [[row[1], int(row[0])] for row in rows],
        })
    return results


@router.post("/annotations")
def annotations(req: _AnnotationRequest) -> list[dict]:
    """Return anomaly window annotations from the evidence table.

    Configure in Grafana: annotation query = $run_id.
    Grafana substitutes $run_id → annotation.query = upload20260618T120000Z.
    We read top_anomaly_windows from executive_context and return regions.
    """
    run_id = str(req.annotation.get("query", "")).strip()
    if not run_id:
        return []

    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM evidence WHERE run_id = %s AND key = 'executive_context'",
            (run_id,),
        ).fetchone()
    if row is None:
        return []

    ctx = row[0]  # psycopg3 auto-deserialises JSONB to dict
    if not isinstance(ctx, dict):
        return []

    windows = ctx.get("top_anomaly_windows") or []
    result: list[dict] = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        try:
            from_key = "from" if "from" in window else "from_"
            start = datetime.fromisoformat(str(window[from_key]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(window["to"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        start -= timedelta(minutes=_ANOMALY_PADDING_MINUTES)
        end += timedelta(minutes=_ANOMALY_PADDING_MINUTES)
        result.append({
            "annotation": req.annotation,
            "time": _dt_to_ms(start),
            "timeEnd": _dt_to_ms(end),
            "isRegion": True,
            "title": str(window.get("metric") or "Anomaly"),
            "text": "",
            "tags": ["anomaly"],
        })
    return result
