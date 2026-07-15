from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from backend.app.db.connection import db_conn

McpTransport = Literal["http", "stdio_template"]
_CONNECTOR_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

STDIO_TEMPLATES: dict[str, dict[str, Any]] = {
    "test-ping-mcp": {
        "label": "Local test MCP (ping/echo)",
        "description": (
            "Shipped with Mongo Debugger — no secrets. Tools: test_ping, test_echo. "
            "Enable on the run page to verify operator MCP wiring."
        ),
        "command": "uv",
        "args": [
            "run",
            "python",
            "simagix-workspace/operator/mcp_connectors/test_mcp_server.py",
        ],
        "required_env": [],
    },
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


def _validate_http_mcp_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.netloc:
        raise ValueError("HTTP MCP connectors must use a valid URL with a host")
    if parsed.scheme == "https":
        return url.strip()
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return url.strip()
    raise ValueError(
        "HTTP MCP connectors must use https:// or local http://127.0.0.1 / http://localhost"
    )


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
        url = _validate_http_mcp_url(str(payload.get("url") or ""))
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
        # workspace_root kept for call-site compatibility; storage is PG.
        pass

    def load(self) -> list[McpConnectorRecord]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT data FROM mcp_connectors ORDER BY id"
            ).fetchall()
        return [McpConnectorRecord.from_dict(row[0]) for row in rows]

    def list_connectors(self) -> list[McpConnectorRecord]:
        return self.load()

    def get(self, connector_id: str) -> McpConnectorRecord | None:
        normalized = _validate_connector_id(connector_id)
        with db_conn() as conn:
            row = conn.execute(
                "SELECT data FROM mcp_connectors WHERE id = %s", (normalized,)
            ).fetchone()
        if row is None:
            return None
        return McpConnectorRecord.from_dict(row[0])

    def upsert(self, payload: dict[str, Any]) -> McpConnectorRecord:
        record = validate_connector_payload(payload)
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO mcp_connectors (id, data, updated_at)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data,"
                " updated_at = EXCLUDED.updated_at",
                (record.id, json.dumps(record.to_dict()), time.time()),
            )
        return record

    def delete(self, connector_id: str) -> bool:
        normalized = _validate_connector_id(connector_id)
        with db_conn() as conn:
            cur = conn.execute(
                "DELETE FROM mcp_connectors WHERE id = %s", (normalized,)
            )
        return (cur.rowcount or 0) > 0

    def resolve_enabled(self, connector_ids: list[str]) -> list[McpConnectorRecord]:
        if not connector_ids:
            return []
        normalized = [_validate_connector_id(raw_id) for raw_id in connector_ids]
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT data FROM mcp_connectors WHERE id = ANY(%s)", (normalized,)
            ).fetchall()
        registry = {McpConnectorRecord.from_dict(row[0]).id: McpConnectorRecord.from_dict(row[0]) for row in rows}
        resolved: list[McpConnectorRecord] = []
        for nid in normalized:
            item = registry.get(nid)
            if item is None:
                raise ValueError(f"Unknown MCP connector: {nid}")
            resolved.append(item)
        return resolved
