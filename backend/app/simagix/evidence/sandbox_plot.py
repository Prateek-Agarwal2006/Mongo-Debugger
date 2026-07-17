"""Execute LLM-authored plotting code in a Daytona sandbox.

Security model: LLM-written code never runs in the pod. The pod-side code
(this module) does the privileged work — read series from PG, store the PNG —
and pushes only a data CSV into an ephemeral Daytona microVM where the
untrusted script runs. The sandbox has no DB credentials and no cluster
access; it sees data.csv and must produce chart.png.

Script contract (documented to the LLM in the MCP tool + metric-plotter skill):
- read ``data.csv`` from the working directory (columns: ``ts`` epoch seconds
  + one column per metric path, cells may be empty)
- write the figure to ``chart.png`` in the working directory
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.simagix.evidence.chart_tools import (
    MAX_PATHS_PER_CHART,
    fetch_series,
    series_to_csv,
    store_chart_png,
)

logger = logging.getLogger(__name__)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_SCRIPT_TIMEOUT_SECONDS = 120
_SANDBOX_CREATE_TIMEOUT_SECONDS = 60


def _sandbox_client():
    """Build a Daytona client, or return (None, error_message)."""
    api_key = get_settings().daytona_api_key
    if not api_key:
        return None, (
            "Daytona sandbox is not configured (DAYTONA_API_KEY missing) — charts are "
            "unavailable for this run. Note the absence of a chart in the finding's "
            "contributing_factors instead of retrying."
        )
    try:
        from daytona import Daytona, DaytonaConfig
    except ImportError:
        return None, "daytona SDK is not installed on the server — charts unavailable"
    return Daytona(DaytonaConfig(api_key=api_key)), None


def execute_plot_script(
    run_id: str,
    workspace_root: Path | None,
    paths: list[str],
    start_ts: float,
    end_ts: float,
    script: str,
    finding_name: str | None = None,
) -> dict[str, Any]:
    """Fetch series → run the script in a Daytona sandbox → store chart.png.

    Returns {"chart_id": ...} on success, or {"error": ...} the LLM can act on
    (fix the script and retry, or record the failure in the report).
    """
    if not paths:
        return {"error": "paths must not be empty"}
    paths = paths[:MAX_PATHS_PER_CHART]
    if end_ts <= start_ts:
        return {"error": "end_ts must be greater than start_ts"}
    if not script or not script.strip():
        return {"error": "script must not be empty"}
    if "chart.png" not in script:
        return {"error": "script must save the figure to chart.png (see the script contract)"}

    series = fetch_series(run_id, workspace_root, paths, start_ts, end_ts)
    if not series:
        return {
            "error": "no data points found for the requested paths/window — chart not created",
            "paths": paths,
        }
    csv_text = series_to_csv(series)
    total_points = sum(len(pts) for pts in series.values())

    client, err = _sandbox_client()
    if err:
        return {"error": err}

    try:
        sandbox = client.create(timeout=_SANDBOX_CREATE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - surface any sandbox-service failure to the LLM
        logger.warning("Daytona sandbox creation failed: %s", exc)
        return {"error": f"sandbox creation failed: {exc}"}

    try:
        sandbox.fs.upload_file(csv_text.encode("utf-8"), "data.csv")
        run = sandbox.process.code_run(script, timeout=_SCRIPT_TIMEOUT_SECONDS)
        if run.exit_code != 0:
            output = (run.result or "").strip()
            return {
                "error": "plot script failed in the sandbox — fix the script and call again",
                "exit_code": run.exit_code,
                "output_tail": output[-1500:],
            }
        png = sandbox.fs.download_file("chart.png")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Daytona sandbox execution failed for run %s: %s", run_id, exc)
        return {"error": f"sandbox execution failed: {exc}"}
    finally:
        try:
            sandbox.delete()
        except Exception:  # noqa: BLE001 - sandbox auto-expires; deletion is best-effort
            logger.warning("Failed to delete Daytona sandbox for run %s", run_id)

    if not png or png[: len(_PNG_MAGIC)] != _PNG_MAGIC:
        return {
            "error": "script completed but chart.png is missing or not a valid PNG — "
            "ensure the script calls fig.savefig('chart.png')",
        }

    chart_id = store_chart_png(run_id, png)
    window_label = (
        f"{datetime.fromtimestamp(start_ts, tz=timezone.utc):%Y-%m-%dT%H:%MZ}"
        f" → {datetime.fromtimestamp(end_ts, tz=timezone.utc):%Y-%m-%dT%H:%MZ}"
    )
    return {
        "chart_id": chart_id,
        "paths_plotted": sorted(series.keys()),
        "points_plotted": total_points,
        "time_window": window_label,
        "finding_name": finding_name,
        "png_bytes": len(png),
        "note": (
            "Set this chart_id on the matching finding_analyses entry and append an entry "
            "to the report charts array."
        ),
    }
