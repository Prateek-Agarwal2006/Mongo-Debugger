"""execute_plot_script: Daytona sandbox flow with the SDK mocked.

The real sandbox is exercised by the live smoke test (needs DAYTONA_API_KEY);
these tests pin the pod-side contract: validation, CSV push, error surfacing,
PNG storage. LLM code must never run in-process — nothing here exec()s the
script.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app.db.connection import db_conn
from backend.app.simagix.evidence.chart_tools import load_chart_png
from backend.app.simagix.evidence.sandbox_plot import execute_plot_script

_RUN = "sandboxtest20260717T000000Z"
_PNG = b"\x89PNG\r\n\x1a\n" + b"fakepngbody"
_SCRIPT = "import matplotlib\n...\nfig.savefig('chart.png')\n"
_WINDOW = (1_780_000_000.0, 1_780_000_100.0)


@pytest.fixture(autouse=True)
def _daytona_key_configured(monkeypatch: pytest.MonkeyPatch):
    from backend.app.core.config import get_settings

    monkeypatch.setenv("DAYTONA_API_KEY", "dtn_test_key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def _seed_metric_rows():
    base_ms = 1_780_000_000_000
    with db_conn() as conn:
        for i in range(10):
            conn.execute(
                "INSERT INTO metrics (run_id, name, ts, value) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (_RUN, "cache_used", base_ms + i * 1000, 100.0 + i),
            )
    yield
    with db_conn() as conn:
        conn.execute("DELETE FROM metrics WHERE run_id = %s", (_RUN,))
        conn.execute("DELETE FROM raw_files WHERE run_id = %s", (_RUN,))


def _mock_sandbox(exit_code: int = 0, png: bytes | None = _PNG, output: str = "") -> MagicMock:
    sandbox = MagicMock()
    sandbox.process.code_run.return_value = SimpleNamespace(exit_code=exit_code, result=output)
    sandbox.fs.download_file.return_value = png
    return sandbox


def _patch_client(sandbox: MagicMock):
    client = MagicMock()
    client.create.return_value = sandbox
    return patch(
        "backend.app.simagix.evidence.sandbox_plot._sandbox_client",
        return_value=(client, None),
    )


# ── validation (no sandbox contact) ──────────────────────────────────────────

def test_empty_paths_rejected() -> None:
    assert "error" in execute_plot_script(_RUN, None, [], *_WINDOW, _SCRIPT)


def test_bad_window_rejected() -> None:
    assert "error" in execute_plot_script(_RUN, None, ["m"], 2.0, 1.0, _SCRIPT)


def test_empty_script_rejected() -> None:
    assert "error" in execute_plot_script(_RUN, None, ["m"], *_WINDOW, "   ")


def test_script_without_chart_png_rejected() -> None:
    result = execute_plot_script(_RUN, None, ["m"], *_WINDOW, "print('hi')")
    assert "chart.png" in result["error"]


def test_no_data_returns_error_without_sandbox() -> None:
    sandbox = _mock_sandbox()
    with _patch_client(sandbox):
        result = execute_plot_script(_RUN, None, ["nonexistent"], *_WINDOW, _SCRIPT)
    assert "no data points" in result["error"]
    sandbox.process.code_run.assert_not_called()


def test_missing_api_key_reports_unconfigured(monkeypatch: pytest.MonkeyPatch, _seed_metric_rows) -> None:
    from backend.app.core.config import get_settings

    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    get_settings.cache_clear()
    result = execute_plot_script(_RUN, None, ["cache_used"], *_WINDOW, _SCRIPT)
    assert "not configured" in result["error"]


# ── sandbox flow ──────────────────────────────────────────────────────────────

def test_success_stores_png_and_deletes_sandbox(_seed_metric_rows) -> None:
    sandbox = _mock_sandbox()
    with _patch_client(sandbox):
        result = execute_plot_script(
            _RUN, None, ["cache_used"], *_WINDOW, _SCRIPT, finding_name="cache pressure"
        )

    assert "error" not in result, result
    assert result["points_plotted"] == 10
    assert result["finding_name"] == "cache pressure"
    assert load_chart_png(_RUN, result["chart_id"]) == _PNG

    # CSV pushed before execution; sandbox always cleaned up.
    upload_args = sandbox.fs.upload_file.call_args[0]
    assert upload_args[1] == "data.csv"
    csv_text = upload_args[0].decode()
    assert csv_text.startswith("ts,cache_used\n")
    assert len(csv_text.strip().split("\n")) == 11
    sandbox.delete.assert_called_once()

    # The LLM script goes to the sandbox verbatim — never executed in-process.
    assert sandbox.process.code_run.call_args[0][0] == _SCRIPT


def test_script_failure_surfaces_output_tail(_seed_metric_rows) -> None:
    sandbox = _mock_sandbox(exit_code=1, output="Traceback: NameError: fig")
    with _patch_client(sandbox):
        result = execute_plot_script(_RUN, None, ["cache_used"], *_WINDOW, _SCRIPT)

    assert "fix the script" in result["error"]
    assert "NameError" in result["output_tail"]
    sandbox.fs.download_file.assert_not_called()
    sandbox.delete.assert_called_once()


def test_invalid_png_rejected(_seed_metric_rows) -> None:
    sandbox = _mock_sandbox(png=b"not a png")
    with _patch_client(sandbox):
        result = execute_plot_script(_RUN, None, ["cache_used"], *_WINDOW, _SCRIPT)
    assert "not a valid PNG" in result["error"]
    sandbox.delete.assert_called_once()


def test_sandbox_exception_cleaned_up(_seed_metric_rows) -> None:
    sandbox = _mock_sandbox()
    sandbox.process.code_run.side_effect = RuntimeError("connection reset")
    with _patch_client(sandbox):
        result = execute_plot_script(_RUN, None, ["cache_used"], *_WINDOW, _SCRIPT)
    assert "sandbox execution failed" in result["error"]
    sandbox.delete.assert_called_once()
