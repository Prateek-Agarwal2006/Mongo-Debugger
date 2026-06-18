from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.core.config import Settings, get_settings


class GrafanaStackManager:
    def __init__(self, workspace_root: Path, settings: Settings | None = None) -> None:
        self.workspace = RunWorkspace(workspace_root)
        self.workspace_root = self.workspace.root
        self.settings = settings or get_settings()
        self.compose_file = self.workspace.grafana_compose_file()

    def is_ftdc_api_up(self) -> bool:
        url = f"{self.settings.ftdc_api_url.rstrip('/')}/"
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def is_grafana_up(self) -> bool:
        url = f"{self.settings.grafana_url.rstrip('/')}/api/health"
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

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

    def start(self) -> None:
        if not self.compose_file.exists():
            raise FileNotFoundError(f"Grafana compose file not found: {self.compose_file}")
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(self.compose_file),
                "up",
                "-d",
                "--build",
            ],
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

    def ensure_running(self) -> dict[str, bool]:
        ftdc_up = self.is_ftdc_api_up()
        grafana_up = self.is_grafana_up()
        if not ftdc_up or not grafana_up:
            self.start()
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
