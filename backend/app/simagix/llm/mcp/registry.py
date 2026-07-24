from __future__ import annotations

import sys
from typing import Any

from backend.app.core.config import Settings
from backend.app.core.run_workspace import repo_root
from backend.app.simagix.evidence.hatchet_tools import hatchet_evidence_available
from backend.app.simagix.llm.mcp.connectors import (
    McpConnectorRegistry,
    STDIO_TEMPLATES,
    McpConnectorRecord,
)
from backend.app.simagix.llm.mcp.specs import ADK_MCP_STDIO_TIMEOUT_SEC, McpServerSpec
from backend.app.simagix.llm.session import Phase2Session

EVIDENCE_SERVER_MODULE = "backend.app.simagix.llm.mcp.servers.evidence"
GRAYLOG_SERVER_MODULE = "backend.app.simagix.llm.mcp.servers.graylog"
HATCHET_SERVER_MODULE = "backend.app.simagix.llm.mcp.servers.hatchet"

try:
    from cursor_sdk import HttpMcpServerConfig, StdioMcpServerConfig
except ImportError:  # pragma: no cover - optional dependency
    HttpMcpServerConfig = None  # type: ignore[assignment,misc]
    StdioMcpServerConfig = None  # type: ignore[assignment,misc]

try:
    from google.adk.tools.mcp_tool import (
        McpToolset,
        StdioConnectionParams,
        StreamableHTTPConnectionParams,
    )
    from mcp.client.stdio import StdioServerParameters
except ImportError:  # pragma: no cover - optional dependency
    McpToolset = None  # type: ignore[assignment,misc]
    StdioConnectionParams = None  # type: ignore[assignment,misc]
    StreamableHTTPConnectionParams = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]


def _stdio_python_module(module: str, *, env: dict[str, str], cwd: str) -> McpServerSpec:
    return McpServerSpec(
        server_id=_server_id_for_module(module),
        transport="stdio",
        command=sys.executable,
        args=["-m", module],
        env=env,
        cwd=cwd,
    )


def _server_id_for_module(module: str) -> str:
    if module.endswith(".evidence"):
        return "simagix-evidence"
    if module.endswith(".graylog"):
        return "graylog"
    if module.endswith(".hatchet"):
        return "hatchet-evidence"
    return module.rsplit(".", maxsplit=1)[-1]


def _connector_to_spec(record: McpConnectorRecord) -> McpServerSpec:
    if record.transport == "http":
        if not record.url:
            raise ValueError(f"HTTP connector {record.id} is missing url")
        return McpServerSpec(
            server_id=record.id,
            transport="http",
            url=record.url,
            headers=dict(record.headers or {}),
        )

    template_id = record.template_id or ""
    template = STDIO_TEMPLATES.get(template_id)
    if template is None:
        raise ValueError(f"Unknown stdio template for connector {record.id}")
    return McpServerSpec(
        server_id=record.id,
        transport="stdio",
        command=str(template["command"]),
        args=[str(arg) for arg in template["args"]],
        env=dict(record.env),
    )


def build_mcp_server_specs(
    session: Phase2Session,
    settings: Settings,
    *,
    enabled_mcp_ids: list[str] | None = None,
    include_builtins: bool = True,
) -> list[McpServerSpec]:
    """Build ordered MCP server specs for a Phase 2 session."""
    specs: list[McpServerSpec] = []
    if not include_builtins:
        enabled = enabled_mcp_ids or []
        if not enabled:
            return specs

    env = session.mcp_server_env()
    # Builtin servers are `python -m backend…` — cwd must be the code root (/app in
    # Kind), not DATA_ROOT. Workspace path travels via SIMAGIX_WORKSPACE_ROOT in env.
    module_cwd = str(repo_root())

    if include_builtins:
        specs.append(_stdio_python_module(EVIDENCE_SERVER_MODULE, env=env, cwd=module_cwd))
        if settings.graylog_api_url and settings.graylog_api_token:
            graylog_env = {
                **env,
                "GRAYLOG_API_URL": settings.graylog_api_url,
                "GRAYLOG_API_TOKEN": settings.graylog_api_token,
                "GRAYLOG_AUTH_MODE": settings.graylog_auth_mode,
                "GRAYLOG_DEFAULT_QUERY": settings.graylog_default_query,
                "GRAYLOG_SEARCH_LIMIT": str(settings.graylog_search_limit),
            }
            specs.append(
                _stdio_python_module(GRAYLOG_SERVER_MODULE, env=graylog_env, cwd=module_cwd)
            )
        if hatchet_evidence_available(session.run_id):
            specs.append(_stdio_python_module(HATCHET_SERVER_MODULE, env=env, cwd=module_cwd))

    if enabled_mcp_ids:
        registry = McpConnectorRegistry(session.workspace_root)
        for record in registry.resolve_enabled(enabled_mcp_ids):
            specs.append(_connector_to_spec(record))

    return specs


def to_cursor_sdk_servers(specs: list[McpServerSpec]) -> dict[str, Any]:
    if HttpMcpServerConfig is None or StdioMcpServerConfig is None:
        raise RuntimeError("cursor-sdk is not installed")

    servers: dict[str, Any] = {}
    for spec in specs:
        if spec.transport == "http":
            if not spec.url:
                raise ValueError(f"HTTP MCP spec {spec.server_id} missing url")
            servers[spec.server_id] = HttpMcpServerConfig(
                url=spec.url,
                headers=spec.headers or None,
            )
        else:
            if not spec.command:
                raise ValueError(f"Stdio MCP spec {spec.server_id} missing command")
            servers[spec.server_id] = StdioMcpServerConfig(
                command=spec.command,
                args=list(spec.args),
                env=spec.env or None,
                cwd=spec.cwd,
            )
    return servers


def build_user_mcp_server_specs(
    workspace_root,
    connector_ids: list[str] | None,
) -> list[McpServerSpec]:
    """Operator WorkArea connectors only (no built-ins)."""
    if not connector_ids:
        return []
    registry = McpConnectorRegistry(workspace_root)
    return [_connector_to_spec(record) for record in registry.resolve_enabled(connector_ids)]


def build_user_mcp_servers(
    workspace_root,
    connector_ids: list[str] | None,
) -> dict[str, Any]:
    """Cursor SDK dict for WorkArea connectors only (backward-compatible helper)."""
    specs = build_user_mcp_server_specs(workspace_root, connector_ids)
    if not specs:
        return {}
    return to_cursor_sdk_servers(specs)


def to_agent_sdk_servers(specs: list[McpServerSpec]) -> dict[str, Any]:
    """Build claude-agent-sdk McpStdioServerConfig / McpHttpServerConfig dicts."""
    try:
        from claude_agent_sdk.types import McpHttpServerConfig, McpStdioServerConfig
    except ImportError:
        raise RuntimeError("claude-agent-sdk is not installed")

    servers: dict[str, Any] = {}
    for spec in specs:
        if spec.transport == "http":
            if not spec.url:
                raise ValueError(f"HTTP MCP spec {spec.server_id} missing url")
            cfg: McpHttpServerConfig = {"type": "http", "url": spec.url}
            if spec.headers:
                cfg["headers"] = spec.headers
            servers[spec.server_id] = cfg
        else:
            if not spec.command:
                raise ValueError(f"Stdio MCP spec {spec.server_id} missing command")
            scfg: McpStdioServerConfig = {"command": spec.command}
            if spec.args:
                scfg["args"] = list(spec.args)
            if spec.env:
                scfg["env"] = spec.env
            servers[spec.server_id] = scfg
    return servers


def to_adk_mcp_toolsets(specs: list[McpServerSpec]) -> list[Any]:
    """Build native ADK McpToolset instances from provider-neutral specs."""
    if McpToolset is None or StdioConnectionParams is None:
        raise RuntimeError("google-adk is not installed")
    if StreamableHTTPConnectionParams is None or StdioServerParameters is None:
        raise RuntimeError("google-adk MCP dependencies are not installed")

    toolsets: list[Any] = []
    for spec in specs:
        if spec.transport == "http":
            if not spec.url:
                raise ValueError(f"HTTP MCP spec {spec.server_id} missing url")
            params = StreamableHTTPConnectionParams(
                url=spec.url,
                headers=spec.headers or None,
            )
        else:
            if not spec.command:
                raise ValueError(f"Stdio MCP spec {spec.server_id} missing command")
            params = StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=spec.command,
                    args=list(spec.args),
                    env=spec.env or None,
                    cwd=spec.cwd,
                ),
                timeout=ADK_MCP_STDIO_TIMEOUT_SEC,
            )
        toolsets.append(McpToolset(connection_params=params))
    return toolsets
