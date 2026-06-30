from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.tool_trace import ToolTraceCollector, ToolTraceEntry, ToolTracePhase

_BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def _parse_allowlist_suffixes(settings: Settings | None = None) -> tuple[str, ...] | None:
    settings = settings or get_settings()
    raw = (settings.phase2_web_allowlist_suffixes or "").strip()
    if not raw:
        return None
    parts = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return tuple(parts) if parts else None


def _host_on_allowlist(host: str, suffixes: tuple[str, ...]) -> bool:
    for suffix in suffixes:
        bare = suffix.lstrip(".")
        if host == bare or host.endswith(f".{bare}") or host.endswith(suffix):
            return True
    return False


def _host_blocked_by_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return True
    return str(addr) == "169.254.169.254"


def validate_web_fetch_url(url: str, *, settings: Settings | None = None) -> str:
    """Validate HTTPS URL for trusted web fetch. Returns normalized URL or raises ValueError."""
    normalized = url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https":
        raise ValueError("url must use https://")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("url must include a host")
    if host in _BLOCKED_HOSTS:
        raise ValueError("url host not allowed")
    if _host_blocked_by_ip(host):
        raise ValueError("url host not allowed")

    allowlist = _parse_allowlist_suffixes(settings)
    if allowlist is not None and not _host_on_allowlist(host, allowlist):
        raise ValueError("url host not on allowlist")
    return normalized


def fetch_https_text(url: str, *, settings: Settings | None = None) -> str:
    """Fetch HTTPS page body text after policy validation."""
    settings = settings or get_settings()
    validated = validate_web_fetch_url(url, settings=settings)
    request = Request(validated, headers={"User-Agent": "mongo-debugger-rca/1.0"})
    timeout = settings.phase2_web_fetch_timeout_s
    max_bytes = settings.phase2_web_fetch_max_bytes
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(max_bytes)
    return raw.decode("utf-8", errors="replace")


def format_fetch_result(url: str, body: str) -> dict[str, Any]:
    excerpt = " ".join(body.split())[:2000]
    return {"url": url, "excerpt": excerpt, "bytes": len(body)}


def execute_web_fetch(
    url: str,
    *,
    settings: Settings | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Run fetch; return (result dict, status, excerpt for trace)."""
    settings = settings or get_settings()
    try:
        validated = validate_web_fetch_url(url, settings=settings)
        body = fetch_https_text(validated, settings=settings)
        result = format_fetch_result(validated, body)
        return result, "completed", result["excerpt"]
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        safe_url = url.strip() or url
        message = str(exc)
        return {"url": safe_url, "error": message}, "error", message


def build_web_fetch_tool(settings: Settings | None = None) -> Callable[..., dict[str, Any]]:
    resolved = settings or get_settings()

    def web_fetch(url: str) -> dict[str, Any]:
        """Fetch trusted HTTPS documentation (same policy as Cursor web_fetch)."""
        result, _status, _excerpt = execute_web_fetch(url, settings=resolved)
        return result

    return web_fetch


def build_cursor_sdk_web_tools(
    trace: ToolTraceCollector,
    phase: ToolTracePhase,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Custom Cursor SDK tools for HTTPS fetch (shows as Web in tool trace)."""
    try:
        from cursor_sdk import CustomTool
    except ImportError:  # pragma: no cover
        return {}

    resolved_settings = settings or get_settings()

    def web_fetch(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        url = str(args.get("url") or "").strip()
        call_id = getattr(ctx, "tool_call_id", None)
        result, status, excerpt = execute_web_fetch(url, settings=resolved_settings)
        trace.append_entry(
            ToolTraceEntry(
                phase=phase,
                timestamp=datetime.now(timezone.utc).isoformat(),
                tool_name="web_fetch",
                category="web",
                status=status,
                call_id=str(call_id) if call_id else None,
                args_summary=json.dumps({"url": url})[:240],
                result_summary=excerpt[:240] if excerpt else "",
            )
        )
        trace.save()
        return result

    return {
        "web_fetch": CustomTool(
            execute=web_fetch,
            description=(
                "Fetch trusted HTTPS documentation or engineering sources. "
                "Call before citing a URL in web_insights, evidence_citations, or reference_urls."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full https URL to fetch",
                    }
                },
                "required": ["url"],
            },
        )
    }
