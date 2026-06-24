from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.grafana.stack import GrafanaStackManager, _HEALTH_CACHE_TTL_SECONDS


@pytest.fixture
def stack(tmp_path: Path) -> GrafanaStackManager:
    simagix = tmp_path / "simagix-workspace"
    (simagix / "docker").mkdir(parents=True)
    compose = simagix / "docker/grafana-compose.yaml"
    compose.write_text("services:\n  ftdc:\n    image: test\n", encoding="utf-8")
    return GrafanaStackManager(tmp_path)


def test_health_cache_returns_true_on_timeout_after_recent_success(stack: GrafanaStackManager) -> None:
    stack._health_cache["ftdc_api"] = (True, time.monotonic())
    with patch("urllib.request.urlopen", side_effect=TimeoutError("busy")):
        assert stack.is_ftdc_api_up() is True


def test_health_cache_expires(stack: GrafanaStackManager) -> None:
    stack._health_cache["ftdc_api"] = (True, time.monotonic() - _HEALTH_CACHE_TTL_SECONDS - 1)
    with patch("urllib.request.urlopen", side_effect=TimeoutError("busy")):
        assert stack.is_ftdc_api_up() is False


def test_ensure_stack_ready_waits_before_restarting_ftdc(stack: GrafanaStackManager) -> None:
    with (
        patch.object(stack, "is_grafana_up", return_value=True),
        patch.object(stack, "is_ftdc_api_up", side_effect=[False, False, True]),
        patch.object(stack, "start_ftdc_only") as mock_ftdc,
        patch.object(stack, "start") as mock_start,
        patch("backend.app.grafana.stack.time.sleep"),
    ):
        status = stack.ensure_stack_ready_for_load()

    mock_start.assert_not_called()
    mock_ftdc.assert_not_called()
    assert status == {"grafana": True, "ftdc_api": True}


def test_ensure_stack_ready_restarts_ftdc_after_wait(stack: GrafanaStackManager) -> None:
    with (
        patch.object(stack, "is_grafana_up", return_value=True),
        patch.object(stack, "is_ftdc_api_up", return_value=False),
        patch.object(stack, "start_ftdc_only") as mock_ftdc,
        patch.object(stack, "_wait_for_services", return_value={"ftdc_api": True, "grafana": True}),
        patch("backend.app.grafana.stack.time.sleep"),
    ):
        status = stack.ensure_stack_ready_for_load()

    mock_ftdc.assert_called_once()
    assert status["ftdc_api"] is True


def test_ensure_running_restarts_ftdc_only_when_grafana_up(stack: GrafanaStackManager) -> None:
    with (
        patch.object(stack, "is_ftdc_api_up", side_effect=[False, True]),
        patch.object(stack, "is_grafana_up", return_value=True),
        patch.object(stack, "start_ftdc_only") as mock_ftdc,
        patch.object(stack, "start") as mock_start,
    ):
        status = stack.ensure_running()

    mock_ftdc.assert_called_once()
    mock_start.assert_not_called()
    assert status == {"ftdc_api": True, "grafana": True}


def test_ensure_running_starts_full_stack_without_build(stack: GrafanaStackManager) -> None:
    with (
        patch.object(stack, "is_ftdc_api_up", side_effect=[False, True]),
        patch.object(stack, "is_grafana_up", side_effect=[False, True]),
        patch.object(stack, "start_ftdc_only") as mock_ftdc,
        patch.object(stack, "start") as mock_start,
    ):
        stack.ensure_running()

    mock_start.assert_called_once_with(build=False)
    mock_ftdc.assert_not_called()


def test_compose_up_omits_build_by_default(stack: GrafanaStackManager) -> None:
    from unittest.mock import MagicMock

    with patch("backend.app.grafana.stack.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        stack._compose_up()

    command = mock_run.call_args.args[0]
    assert command[-1] == "-d"
    assert "--build" not in command
