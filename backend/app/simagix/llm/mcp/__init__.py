"""Shared MCP registry, connectors, client bridge, and server subprocess modules."""

from backend.app.simagix.llm.mcp.connectors import McpConnectorRegistry, list_stdio_templates
from backend.app.simagix.llm.mcp.registry import build_mcp_server_specs, to_cursor_sdk_servers
from backend.app.simagix.llm.mcp.specs import McpServerSpec

__all__ = [
    "McpConnectorRegistry",
    "McpServerSpec",
    "build_mcp_server_specs",
    "list_stdio_templates",
    "to_cursor_sdk_servers",
]
