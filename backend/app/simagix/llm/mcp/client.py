from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, AsyncIterator, Callable

import mcp.types as mcp_types
from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters
from mcp.client.stdio import StdioServerParameters

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.mcp.specs import BARE_TOOL_MCP_SERVER_NAMES, McpServerSpec
from backend.app.simagix.llm.web_fetch import execute_web_fetch

try:
    from google.adk.tools.base_tool import BaseTool
except ImportError:  # pragma: no cover
    BaseTool = Any  # type: ignore[assignment,misc]


def _component_name_hook(name: str, server_info: mcp_types.Implementation) -> str:
    server_name = (server_info.name or "").strip()
    if server_name in BARE_TOOL_MCP_SERVER_NAMES:
        return name
    if server_name:
        return f"{server_name}/{name}"
    return name


def _spec_to_server_params(spec: McpServerSpec) -> StdioServerParameters | StreamableHttpParameters:
    if spec.transport == "http":
        if not spec.url:
            raise ValueError(f"MCP HTTP spec {spec.server_id} missing url")
        return StreamableHttpParameters(url=spec.url, headers=spec.headers or None)
    if not spec.command:
        raise ValueError(f"MCP stdio spec {spec.server_id} missing command")
    return StdioServerParameters(
        command=spec.command,
        args=list(spec.args),
        env=spec.env or None,
        cwd=spec.cwd,
    )


def _tool_result_to_python(result: mcp_types.CallToolResult) -> Any:
    if result.isError:
        text_parts = [
            block.text
            for block in (result.content or [])
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        ]
        message = " ".join(text_parts).strip() or "MCP tool error"
        raise RuntimeError(message)
    if not result.content:
        return {}
    if len(result.content) == 1 and getattr(result.content[0], "type", None) == "text":
        text = getattr(result.content[0], "text", "") or ""
        text = text.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
        return {"text": text}
    payload: list[Any] = []
    for block in result.content:
        if getattr(block, "type", None) == "text":
            payload.append(getattr(block, "text", ""))
        else:
            payload.append(block.model_dump() if hasattr(block, "model_dump") else str(block))
    return payload


def _make_sync_tool(
    group: ClientSessionGroup,
    tool_name: str,
    *,
    loop: asyncio.AbstractEventLoop,
    description: str | None,
) -> Callable[..., Any]:
    def _call(**kwargs: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(
            group.call_tool(tool_name, kwargs, read_timeout_seconds=timedelta(seconds=120)),
            loop,
        )
        return _tool_result_to_python(future.result(timeout=125))

    _call.__name__ = tool_name.replace("/", "_")
    _call.__doc__ = description or f"MCP tool {tool_name}"
    return _call


def build_web_fetch_tool(settings: Settings | None = None) -> Callable[..., dict[str, Any]]:
    resolved = settings or get_settings()

    def web_fetch(url: str) -> dict[str, Any]:
        """Fetch trusted HTTPS documentation (same policy as Cursor web_fetch)."""
        result, _status, _excerpt = execute_web_fetch(url, settings=resolved)
        return result

    return web_fetch


@asynccontextmanager
async def mcp_session_group(specs: list[McpServerSpec]) -> AsyncIterator[ClientSessionGroup]:
    group = ClientSessionGroup(component_name_hook=_component_name_hook)
    async with group:
        for spec in specs:
            await group.connect_to_server(_spec_to_server_params(spec))
        yield group


async def build_adk_tools_async(
    specs: list[McpServerSpec],
    *,
    settings: Settings | None = None,
) -> tuple[list[Callable[..., Any]], ClientSessionGroup]:
    """Open MCP sessions and return ADK callables plus the live session group."""
    resolved = settings or get_settings()
    group = ClientSessionGroup(component_name_hook=_component_name_hook)
    await group.__aenter__()
    try:
        for spec in specs:
            await group.connect_to_server(_spec_to_server_params(spec))
    except Exception:
        await group.__aexit__(None, None, None)
        raise

    loop = asyncio.get_running_loop()
    tools: list[Callable[..., Any]] = []
    for tool_name, tool in group.tools.items():
        tools.append(
            _make_sync_tool(group, tool_name, loop=loop, description=tool.description)
        )
    tools.append(build_web_fetch_tool(resolved))
    return tools, group


async def close_mcp_session_group(group: ClientSessionGroup) -> None:
    await group.__aexit__(None, None, None)
