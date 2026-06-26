from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from backend.app.core.run_workspace import RunWorkspace

McpTransport = Literal["http", "stdio_template"]
_CONNECTOR_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

STDIO_TEMPLATES: dict[str, dict[str, Any]] = {
    "github-mcp": {
        "label": "GitHub MCP (Docker)",
        "description": "Official GitHub MCP server via ghcr.io/github/github-mcp-server",
        "command": "docker",
        "args": [
            "run",
            "-i",
            "--rm",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "ghcr.io/github/github-mcp-server",
        ],
        "required_env": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    },
}


@dataclass
class McpConnectorRecord:
    id: str
    name: str
    transport: McpTransport
    description: str = ""
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    template_id: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> McpConnectorRecord:
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            transport=payload["transport"],
            description=str(payload.get("description") or ""),
            url=payload.get("url"),
            headers=dict(payload.get("headers") or {}),
            template_id=payload.get("template_id"),
            env=dict(payload.get("env") or {}),
        )


def operator_mcp_connectors_dir(workspace_root: Path) -> Path:
    return RunWorkspace(workspace_root).simagix_root / "operator" / "mcp_connectors"


def registry_path(workspace_root: Path) -> Path:
    return operator_mcp_connectors_dir(workspace_root) / "registry.json"


def list_stdio_templates() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for template_id, spec in STDIO_TEMPLATES.items():
        items.append(
            {
                "id": template_id,
                "label": spec["label"],
                "description": spec["description"],
                "required_env": list(spec["required_env"]),
            }
        )
    return items


def _validate_connector_id(connector_id: str) -> str:
    normalized = connector_id.strip().lower()
    if not _CONNECTOR_ID_RE.fullmatch(normalized):
        raise ValueError(
            "Connector id must be 1-64 chars: lowercase letters, digits, hyphen, underscore"
        )
    return normalized


def _validate_https_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("HTTP MCP connectors must use a valid https:// URL")
    return url.strip()


def validate_connector_payload(payload: dict[str, Any]) -> McpConnectorRecord:
    connector_id = _validate_connector_id(str(payload.get("id") or payload.get("name") or ""))
    name = str(payload.get("name") or connector_id).strip()
    if not name:
        raise ValueError("Connector name is required")
    transport = payload.get("transport")
    if transport not in {"http", "stdio_template"}:
        raise ValueError("transport must be 'http' or 'stdio_template'")
    description = str(payload.get("description") or "").strip()

    if transport == "http":
        url = _validate_https_url(str(payload.get("url") or ""))
        headers_raw = payload.get("headers") or {}
        if not isinstance(headers_raw, dict):
            raise ValueError("headers must be an object")
        headers = {str(k): str(v) for k, v in headers_raw.items() if str(k).strip()}
        return McpConnectorRecord(
            id=connector_id,
            name=name,
            transport="http",
            description=description,
            url=url,
            headers=headers,
        )

    template_id = str(payload.get("template_id") or "").strip()
    if template_id not in STDIO_TEMPLATES:
        raise ValueError(f"Unknown stdio template: {template_id}")
    template = STDIO_TEMPLATES[template_id]
    env_raw = payload.get("env") or {}
    if not isinstance(env_raw, dict):
        raise ValueError("env must be an object")
    env = {str(k): str(v) for k, v in env_raw.items()}
    missing = [key for key in template["required_env"] if not env.get(key, "").strip()]
    if missing:
        raise ValueError(f"Missing required env for template: {', '.join(missing)}")
    return McpConnectorRecord(
        id=connector_id,
        name=name,
        transport="stdio_template",
        description=description,
        template_id=template_id,
        env=env,
    )


class McpConnectorRegistry:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.path = registry_path(self.workspace_root)

    def load(self) -> list[McpConnectorRecord]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        connectors = payload.get("connectors") or []
        return [McpConnectorRecord.from_dict(item) for item in connectors]

    def save(self, connectors: list[McpConnectorRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"connectors": [item.to_dict() for item in connectors]}
        self.path.write_text(json.dumps(body, indent=2), encoding="utf-8")

    def list_connectors(self) -> list[McpConnectorRecord]:
        return self.load()

    def get(self, connector_id: str) -> McpConnectorRecord | None:
        normalized = _validate_connector_id(connector_id)
        for item in self.load():
            if item.id == normalized:
                return item
        return None

    def upsert(self, payload: dict[str, Any]) -> McpConnectorRecord:
        record = validate_connector_payload(payload)
        connectors = self.load()
        replaced = False
        updated: list[McpConnectorRecord] = []
        for item in connectors:
            if item.id == record.id:
                updated.append(record)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(record)
        self.save(updated)
        return record

    def delete(self, connector_id: str) -> bool:
        normalized = _validate_connector_id(connector_id)
        connectors = self.load()
        remaining = [item for item in connectors if item.id != normalized]
        if len(remaining) == len(connectors):
            return False
        self.save(remaining)
        return True

    def resolve_enabled(self, connector_ids: list[str]) -> list[McpConnectorRecord]:
        if not connector_ids:
            return []
        registry = {item.id: item for item in self.load()}
        resolved: list[McpConnectorRecord] = []
        for raw_id in connector_ids:
            connector_id = _validate_connector_id(raw_id)
            item = registry.get(connector_id)
            if item is None:
                raise ValueError(f"Unknown MCP connector: {connector_id}")
            resolved.append(item)
        return resolved
