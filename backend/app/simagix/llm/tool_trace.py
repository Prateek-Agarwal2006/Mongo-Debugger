from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ToolTraceCategory = Literal["mcp", "web", "local", "shell", "other"]
ToolTracePhase = Literal["investigation", "clarify", "final_rca", "chatbot"]

EVIDENCE_MCP_TOOL_NAMES = frozenset(
    {
        "get_metric_window",
        "get_normalized_series",
        "get_raw_path",
        "list_fallback_metrics",
        "get_budget_status",
        "get_profiler_samples",
        "query_logs_around_window",
    }
)


@dataclass
class ToolTraceEntry:
    phase: ToolTracePhase
    timestamp: str
    tool_name: str
    category: ToolTraceCategory
    status: str
    call_id: str | None = None
    args_summary: str = ""
    result_summary: str = ""
    mcp_server: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_args_dict(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def resolve_tool_identity(tool_name: str, args: Any) -> tuple[str, str | None]:
    """Map Cursor SDK tool payloads to a readable name and MCP server id."""
    name = (tool_name or "").strip()
    lower = name.lower()
    args_dict = _coerce_args_dict(args)

    if lower == "mcp":
        inner = args_dict.get("toolName") or args_dict.get("tool_name")
        provider = args_dict.get("providerIdentifier") or args_dict.get("provider_identifier")
        if inner:
            provider_text = str(provider) if provider else "simagix-evidence"
            return f"{provider_text}/{inner}", provider_text
        return name, None

    marker = "simagix-evidence_"
    if marker in lower:
        inner = name[lower.index(marker) + len(marker) :]
        return f"simagix-evidence/{inner}", "simagix-evidence"

    if "graylog" in lower and "_query_" in lower:
        inner = name.split("_")[-1] if "_" in name else name
        return f"graylog/{inner}", "graylog"

    return name, _extract_mcp_server(name, args)


def classify_tool_category(tool_name: str, args: Any = None) -> ToolTraceCategory:
    args_dict = _coerce_args_dict(args)
    inner_tool = args_dict.get("toolName") or args_dict.get("tool_name")
    if inner_tool in EVIDENCE_MCP_TOOL_NAMES:
        return "mcp"

    display_name, _ = resolve_tool_identity(tool_name, args)
    name = display_name.lower()
    args_text = json.dumps(args, default=str).lower() if args is not None else ""

    if any(token in name for token in ("fetch", "web_search", "websearch", "browse", "internet", "google_search", "web_fetch")):
        return "web"
    if "http://" in args_text or "https://" in args_text:
        return "web"

    if (
        "mcp" in name
        or name.startswith("simagix-evidence/")
        or name.startswith("graylog/")
        or "simagix-evidence" in args_text
        or "graylog" in args_text
    ):
        return "mcp"

    if any(token in name for token in ("shell", "terminal", "bash", "run_terminal")):
        return "shell"

    if any(token in name for token in ("read", "grep", "glob", "semsearch", "semantic", "list_dir", "ls")):
        return "local"

    return "other"


def _summarize_value(value: Any, *, limit: int = 240) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _extract_mcp_server(tool_name: str, args: Any) -> str | None:
    name = (tool_name or "").lower()
    if "simagix-evidence" in name:
        return "simagix-evidence"
    if "graylog" in name:
        return "graylog"
    args_dict = _coerce_args_dict(args)
    provider = args_dict.get("providerIdentifier") or args_dict.get("provider_identifier")
    if provider:
        return str(provider)
    for key in ("server", "mcp_server", "serverName", "server_name"):
        if args_dict.get(key):
            return str(args_dict[key])
    return None


class ToolTraceCollector:
    def __init__(self, path: Path, *, agent_id: str | None = None) -> None:
        self.path = path
        self.agent_id = agent_id
        self._seen_call_ids: set[str] = set()
        self.entries: list[ToolTraceEntry] = []
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.agent_id = payload.get("agent_id") or self.agent_id
        for item in payload.get("entries", []):
            entry = ToolTraceEntry(**item)
            self.entries.append(entry)
            if entry.call_id:
                self._seen_call_ids.add(entry.call_id)

    def record_sdk_message(self, message: Any, phase: ToolTracePhase) -> None:
        msg_type = getattr(message, "type", None)
        if msg_type != "tool_call":
            if isinstance(message, dict) and message.get("type") == "tool_call":
                self._record_from_fields(
                    phase=phase,
                    call_id=str(message.get("call_id") or message.get("callId") or ""),
                    tool_name=str(message.get("name") or ""),
                    status=str(message.get("status") or ""),
                    args=message.get("args"),
                    result=message.get("result"),
                )
            return

        status = str(getattr(message, "status", "") or "")
        if status and status != "completed":
            return

        self._record_from_fields(
            phase=phase,
            call_id=str(getattr(message, "call_id", "") or ""),
            tool_name=str(getattr(message, "name", "") or ""),
            status=status or "completed",
            args=getattr(message, "args", None),
            result=getattr(message, "result", None),
        )

    def _record_from_fields(
        self,
        *,
        phase: ToolTracePhase,
        call_id: str,
        tool_name: str,
        status: str,
        args: Any,
        result: Any,
    ) -> None:
        if not tool_name:
            return
        if call_id and call_id in self._seen_call_ids:
            return

        display_name, mcp_server = resolve_tool_identity(tool_name, args)
        entry = ToolTraceEntry(
            phase=phase,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool_name=display_name,
            category=classify_tool_category(tool_name, args),
            status=status or "completed",
            call_id=call_id or None,
            args_summary=_summarize_value(args),
            result_summary=_summarize_value(result),
            mcp_server=mcp_server or _extract_mcp_server(tool_name, args),
        )
        self.entries.append(entry)
        if call_id:
            self._seen_call_ids.add(call_id)

    def append_entry(self, entry: ToolTraceEntry) -> None:
        if entry.call_id and entry.call_id in self._seen_call_ids:
            return
        self.entries.append(entry)
        if entry.call_id:
            self._seen_call_ids.add(entry.call_id)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "agent_id": self.agent_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "summary": summarize_entries(self.entries),
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def summarize_entries(entries: list[ToolTraceEntry]) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    for entry in entries:
        by_category[entry.category] = by_category.get(entry.category, 0) + 1
        by_phase[entry.phase] = by_phase.get(entry.phase, 0) + 1
    return {
        "total": len(entries),
        "by_category": by_category,
        "by_phase": by_phase,
    }




def adk_tool_trace_identity(tool_name: str) -> tuple[str, ToolTraceCategory, str | None]:
    """Map ADK tool names to normalized trace rows (evidence MCP vs google_search web)."""
    name = (tool_name or "tool").strip()
    lower = name.lower()
    if lower in {"google_search", "google_search_agent"} or "google_search" in lower:
        return "google_search", "web", None
    if name in EVIDENCE_MCP_TOOL_NAMES:
        return f"simagix-evidence/{name}", "mcp", "simagix-evidence"
    category = classify_tool_category(name)
    if category == "mcp":
        return f"simagix-evidence/{name}", "mcp", "simagix-evidence"
    return name, category, None


def record_grounding_metadata(
    trace: ToolTraceCollector,
    phase: ToolTracePhase,
    events: list[Any],
    *,
    seen_call_ids: set[str] | None = None,
) -> None:
    """Record Gemini google_search grounding from ADK events when present."""
    seen = seen_call_ids if seen_call_ids is not None else set()
    for event in events:
        metadata = getattr(event, "grounding_metadata", None)
        if metadata is None:
            continue
        queries = getattr(metadata, "web_search_queries", None) or []
        chunks = getattr(metadata, "grounding_chunks", None) or []
        query_text = ", ".join(str(q) for q in queries if q)
        urls: list[str] = []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            uri = getattr(web, "uri", None) or getattr(web, "title", None)
            if uri:
                urls.append(str(uri))
        if not query_text and not urls:
            continue
        fingerprint = f"{query_text}|{'|'.join(urls[:5])}"
        call_id = f"gemini-grounding-{phase}-{abs(hash(fingerprint))}"
        if call_id in seen:
            continue
        seen.add(call_id)
        trace.append_entry(
            ToolTraceEntry(
                phase=phase,
                timestamp=datetime.now(timezone.utc).isoformat(),
                tool_name="google_search",
                category="web",
                status="completed",
                call_id=call_id,
                args_summary=_summarize_value(query_text or "google_search"),
                result_summary=_summarize_value("; ".join(urls[:5]) if urls else None),
            )
        )


def load_tool_trace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "agent_id": None,
            "entries": [],
            "summary": {"total": 0, "by_category": {}, "by_phase": {}},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    summary = payload.get("summary") or summarize_entries(
        [ToolTraceEntry(**item) for item in entries]
    )
    return {
        "agent_id": payload.get("agent_id"),
        "entries": entries,
        "summary": summary,
    }


def write_mock_tool_trace(path: Path, *, run_id: str, phase: ToolTracePhase) -> None:
    """Deterministic trace rows for mock provider demos."""
    now = datetime.now(timezone.utc).isoformat()
    collector = ToolTraceCollector(path, agent_id="mock-agent-id")
    if phase == "investigation":
        collector.append_entry(
            ToolTraceEntry(
                phase="investigation",
                timestamp=now,
                tool_name="simagix-evidence/get_metric_window",
                category="mcp",
                status="completed",
                call_id=f"mock-{run_id}-inv-mcp-1",
                args_summary='{"metric": "cpu_idle", "limit": 3}',
                mcp_server="simagix-evidence",
            )
        )
        collector.append_entry(
            ToolTraceEntry(
                phase="investigation",
                timestamp=now,
                tool_name="web_search",
                category="web",
                status="completed",
                call_id=f"mock-{run_id}-inv-web-1",
                args_summary="MongoDB replication lag troubleshooting site:mongodb.com/docs",
                result_summary="https://www.mongodb.com/docs/manual/replication/",
            )
        )
    elif phase == "final_rca":
        collector.append_entry(
            ToolTraceEntry(
                phase="final_rca",
                timestamp=now,
                tool_name="fetch",
                category="web",
                status="completed",
                call_id=f"mock-{run_id}-rca-web-1",
                args_summary="https://www.mongodb.com/docs/manual/core/replica-set-oplog/",
                result_summary="Oplog sizing guidance",
            )
        )
    elif phase == "chatbot":
        collector.append_entry(
            ToolTraceEntry(
                phase="chatbot",
                timestamp=now,
                tool_name="web_fetch",
                category="web",
                status="completed",
                call_id=f"mock-{run_id}-chat-web-1",
                args_summary='{"url": "https://www.mongodb.com/docs/manual/"}',
                result_summary="Mock chatbot web fetch",
            )
        )
    collector.save()
