from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.core.config import Settings, get_settings


FTDC_LOCAL_IMAGE = "mongo-debugger/ftdc:local"
_HEALTH_TIMEOUT_SECONDS = 5
_HEALTH_CACHE_TTL_SECONDS = 180

# Shared across all GrafanaStackManager instances. A new manager is created per
# HTTP request, so a per-instance cache never survives long enough to mask a
# transient probe timeout while the single-threaded FTDC API is busy decoding.
_HEALTH_CACHE: dict[str, tuple[bool, float]] = {}


class GrafanaStackManager:
    def __init__(self, workspace_root: Path, settings: Settings | None = None) -> None:
        self.workspace = RunWorkspace(workspace_root)
        self.workspace_root = self.workspace.root
        self.settings = settings or get_settings()
        self.compose_file = self.workspace.grafana_compose_file()
        self._health_cache = _HEALTH_CACHE

    def _probe_http_health(self, cache_key: str, url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=_HEALTH_TIMEOUT_SECONDS) as resp:
                up = resp.status == 200
                if up:
                    self._health_cache[cache_key] = (True, time.monotonic())
                return up
        except Exception:
            # The single-threaded FTDC API can stop answering health probes while
            # it decodes a run. Treat a recent success as still-up so a transient
            # timeout does not hide the dashboard links on reload.
            cached = self._health_cache.get(cache_key)
            if (
                cached
                and cached[0]
                and (time.monotonic() - cached[1]) < _HEALTH_CACHE_TTL_SECONDS
            ):
                return True
            return False

    def is_ftdc_api_up(self) -> bool:
        url = f"{self.settings.ftdc_api_url.rstrip('/')}/"
        return self._probe_http_health("ftdc_api", url)

    def is_grafana_up(self) -> bool:
        url = f"{self.settings.grafana_url.rstrip('/')}/api/health"
        return self._probe_http_health("grafana", url)

    def _wait_for_services(self, *, attempts: int | None = None, delay_seconds: float = 2.0) -> dict[str, bool]:
        if attempts is None:
            attempts = max(1, int(self.settings.grafana_startup_wait_seconds / delay_seconds))
        for _attempt in range(attempts):
            status = {
                "ftdc_api": self.is_ftdc_api_up(),
                "grafana": self.is_grafana_up(),
            }
            if status["ftdc_api"] and status["grafana"]:
                return status
            time.sleep(delay_seconds)
        return {
            "ftdc_api": self.is_ftdc_api_up(),
            "grafana": self.is_grafana_up(),
        }

    def _ftdc_image_present(self) -> bool:
        result = subprocess.run(
            ["docker", "image", "inspect", FTDC_LOCAL_IMAGE],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def _build_ftdc_image_if_needed(self) -> None:
        if self._ftdc_image_present():
            return
        script = self.workspace.simagix_root / "scripts/build-ftdc-local.sh"
        if not script.is_file():
            raise FileNotFoundError(
                f"FTDC image {FTDC_LOCAL_IMAGE} not found and {script} is missing. "
                "Run scripts/setup-simagix-repos.sh then simagix-workspace/scripts/build-ftdc-local.sh"
            )
        result = subprocess.run(
            ["bash", str(script)],
            cwd=self.workspace_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "build-ftdc-local.sh failed").strip()
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=detail,
            )

    def _compose_up(self, *, services: list[str] | None = None, build: bool = False) -> None:
        if not self.compose_file.exists():
            raise FileNotFoundError(f"Grafana compose file not found: {self.compose_file}")
        command = [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "up",
            "-d",
        ]
        if build:
            command.append("--build")
        if services:
            command.extend(services)
        result = subprocess.run(
            command,
            cwd=self.workspace_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "docker compose up failed").strip()
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=detail,
            )

    def start(self, *, build: bool = False) -> None:
        """Start the full Grafana stack. Use build=True only from run-grafana-stack.sh."""
        self._build_ftdc_image_if_needed()
        self._compose_up(build=build)

    def start_ftdc_only(self) -> None:
        """Restart FTDC API without rebuilding or touching Grafana."""
        self._build_ftdc_image_if_needed()
        self._compose_up(services=["ftdc"])

    def ensure_stack_ready_for_load(self) -> dict[str, bool]:
        """Prepare stack for POST /grafana/dir without restarting a busy FTDC decoder."""
        grafana_up = self.is_grafana_up()
        ftdc_up = self.is_ftdc_api_up()
        if not grafana_up:
            self.start(build=False)
            status = self._wait_for_services()
        else:
            status = {"grafana": True, "ftdc_api": ftdc_up}

        if status["grafana"] and not status["ftdc_api"]:
            for _ in range(30):
                if self.is_ftdc_api_up():
                    return {"grafana": True, "ftdc_api": True}
                time.sleep(2)
            self.start_ftdc_only()
            status = self._wait_for_services()

        if not status["ftdc_api"] or not status["grafana"]:
            raise RuntimeError(
                "Grafana stack started but services are not healthy yet. "
                f"ftdc_api={status['ftdc_api']} grafana={status['grafana']}"
            )
        return status

    def ensure_running(self) -> dict[str, bool]:
        ftdc_up = self.is_ftdc_api_up()
        grafana_up = self.is_grafana_up()

        if grafana_up and not ftdc_up:
            # Grafana is fine — only revive FTDC (avoid compose --build killing Grafana).
            self.start_ftdc_only()
            status = self._wait_for_services()
        elif not grafana_up or not ftdc_up:
            self.start(build=False)
            status = self._wait_for_services()
        else:
            status = {"ftdc_api": ftdc_up, "grafana": grafana_up}

        if not status["ftdc_api"] or not status["grafana"]:
            raise RuntimeError(
                "Grafana stack started but services are not healthy yet. "
                f"ftdc_api={status['ftdc_api']} grafana={status['grafana']}"
            )
        return status

    def load_run_data(self, container_input_path: str) -> dict[str, object]:
        url = f"{self.settings.ftdc_api_url.rstrip('/')}/grafana/dir"
        payload = json.dumps({"dir": container_input_path}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = self.settings.ftdc_load_timeout_seconds
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ok") != 1:
            raise RuntimeError(body.get("err", "Failed to load FTDC directory into Grafana API"))
        return body

    def container_path_for_host(self, host_path: Path) -> str:
        rel = host_path.resolve().relative_to(self.workspace_root)
        return f"/workspace/{rel.as_posix()}"

