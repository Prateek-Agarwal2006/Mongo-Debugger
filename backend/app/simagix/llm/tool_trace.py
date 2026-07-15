from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from backend.app.simagix.evidence.hatchet_tools import HATCHET_MCP_TOOL_NAMES

ToolTraceCategory = Literal["mcp", "web", "local", "shell", "other"]
ToolTracePhase = Literal["investigation", "clarify", "final_rca", "chatbot"]

EVIDENCE_MCP_TOOL_NAMES = frozenset(
    {
        "get_metric_window",
        "get_normalized_series",
        "list_fallback_metrics",
        "list_raw_paths",
        "get_raw_window",
        "get_budget_status",
        "query_logs_around_window",
        *HATCHET_MCP_TOOL_NAMES,
    }
)

# Shipped operator test MCP tools (local-test-http / test-ping stdio).
OPERATOR_TEST_MCP_TOOL_NAMES = frozenset({"test_ping", "test_echo"})


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


def _split_operator_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Cursor/ADK prefixed tools: `{connector_id}_{tool}` e.g. local-test-http_test_ping."""
    for inner in OPERATOR_TEST_MCP_TOOL_NAMES:
        marker = f"_{inner}"
        if name.endswith(marker):
            server_id = name[:-len(marker)]
            if server_id:
                return server_id, inner
    if "_" not in name:
        return None
    server_id, inner = name.rsplit("_", 1)
    if not server_id or not inner:
        return None
    if server_id in {"simagix-evidence", "hatchet-evidence", "graylog", "graylog-logs"}:
        if inner in EVIDENCE_MCP_TOOL_NAMES or inner in HATCHET_MCP_TOOL_NAMES:
            return server_id, inner
    return None


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

    split = _split_operator_mcp_tool_name(name)
    if split is not None:
        server_id, inner = split
        return f"{server_id}/{inner}", server_id

    if name in OPERATOR_TEST_MCP_TOOL_NAMES:
        return f"operator-mcp/{name}", "operator-mcp"

    marker = "simagix-evidence_"
    if marker in lower:
        inner = name[lower.index(marker) + len(marker) :]
        return f"simagix-evidence/{inner}", "simagix-evidence"

    hatchet_marker = "hatchet-evidence_"
    if hatchet_marker in lower:
        inner = name[lower.index(hatchet_marker) + len(hatchet_marker) :]
        return f"hatchet-evidence/{inner}", "hatchet-evidence"

    if "graylog" in lower and "_query_" in lower:
        inner = name.split("_")[-1] if "_" in name else name
        return f"graylog/{inner}", "graylog"

    return name, _extract_mcp_server(name, args)


def classify_tool_category(tool_name: str, args: Any = None) -> ToolTraceCategory:
    """Bucket tools for the trace UI using the SDK tool name (Cursor returns ``mcp`` for all MCP)."""
    raw = (tool_name or "").strip()
    lower = raw.lower()
    args_dict = _coerce_args_dict(args)
    args_text = json.dumps(args, default=str).lower() if args is not None else ""

    # Cursor SDK: every operator MCP call uses tool_name "mcp" (connector lives in args).
    if lower == "mcp":
        return "mcp"

    inner_tool = args_dict.get("toolName") or args_dict.get("tool_name")
    if inner_tool in EVIDENCE_MCP_TOOL_NAMES or inner_tool in OPERATOR_TEST_MCP_TOOL_NAMES:
        return "mcp"

    if _split_operator_mcp_tool_name(raw) is not None:
        return "mcp"
    if raw in EVIDENCE_MCP_TOOL_NAMES or raw in HATCHET_MCP_TOOL_NAMES or raw in OPERATOR_TEST_MCP_TOOL_NAMES:
        return "mcp"

    if any(
        token in lower
        for token in ("fetch", "web_search", "websearch", "browse", "internet", "google_search", "web_fetch")
    ):
        return "web"
    if "http://" in args_text or "https://" in args_text:
        return "web"

    if (
        "mcp" in lower
        or lower.startswith("simagix-evidence/")
        or lower.startswith("simagix-evidence_")
        or lower.startswith("hatchet-evidence/")
        or lower.startswith("hatchet-evidence_")
        or lower.startswith("graylog/")
        or lower.startswith("operator-mcp/")
        or "simagix-evidence" in args_text
        or "graylog" in args_text
    ):
        return "mcp"

    if any(token in lower for token in ("shell", "terminal", "bash", "run_terminal")):
        return "shell"

    if any(token in lower for token in ("read", "grep", "glob", "semsearch", "semantic", "list_dir", "ls")):
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
    def __init__(self, run_id: str, llm: str, *, agent_id: str | None = None) -> None:
        self.run_id = run_id
        self.llm = llm
        self.agent_id = agent_id
        self._seen_call_ids: set[str] = set()
        self.entries: list[ToolTraceEntry] = []
        self._load_existing()

    def _load_existing(self) -> None:
        from backend.app.simagix.llm.state import load_state

        payload = load_state(self.run_id, self.llm, "tool_trace")
        if payload is None:
            return
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
        if status and status not in {"completed", "error", "failed"}:
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
        from backend.app.simagix.llm.state import save_state

        payload = {
            "agent_id": self.agent_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "summary": summarize_entries(self.entries),
        }
        save_state(self.run_id, self.llm, "tool_trace", payload)


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




def adk_tool_trace_call_id(
    tool_context: Any,
    phase: ToolTracePhase | None = None,
) -> str | None:
    """Per-tool call id for ADK traces (Cursor SDK uses tool_call.call_id the same way).

    Scope ids by phase — ADK may reuse function_call_id values across separate runs
    (investigation vs final_rca) in the same tool_trace.json file.
    """
    function_call_id = getattr(tool_context, "function_call_id", None)
    if not function_call_id:
        return None
    call_id = str(function_call_id)
    return f"{phase}:{call_id}" if phase else call_id


def adk_tool_trace_status(tool_context: Any, tool_response: Any) -> str:
    """Map ADK tool outcome to trace status (Cursor uses SDK message status)."""
    if getattr(tool_context, "error", None):
        return "error"
    if isinstance(tool_response, dict):
        if tool_response.get("isError") or tool_response.get("error"):
            return "error"
        content = tool_response.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("isError"):
                    return "error"
    return "completed"


def adk_tool_trace_identity(tool_name: str) -> tuple[str, ToolTraceCategory, str | None]:
    """Map ADK tool names to normalized trace rows (MCP client vs web_fetch)."""
    name = (tool_name or "tool").strip()
    lower = name.lower()
    if lower in {"google_search", "google_search_agent"} or "google_search" in lower:
        return "google_search", "web", None
    if lower == "web_fetch":
        return "web_fetch", "web", None

    if "/" in name:
        server, inner = name.split("/", 1)
        display_server = "graylog" if server in {"graylog-logs"} else server
        if inner in HATCHET_MCP_TOOL_NAMES or display_server == "hatchet-evidence":
            return f"hatchet-evidence/{inner}", "mcp", "hatchet-evidence"
        if inner in EVIDENCE_MCP_TOOL_NAMES or display_server == "simagix-evidence":
            return f"simagix-evidence/{inner}", "mcp", "simagix-evidence"
        if display_server in {"graylog", "simagix-evidence", "hatchet-evidence"}:
            return f"{display_server}/{inner}", "mcp", display_server
        return name, "mcp", display_server

    if name in HATCHET_MCP_TOOL_NAMES:
        return f"hatchet-evidence/{name}", "mcp", "hatchet-evidence"
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


def load_tool_trace(run_id: str, llm: str) -> dict[str, Any]:
    from backend.app.simagix.llm.state import load_state

    payload = load_state(run_id, llm, "tool_trace")
    if payload is None:
        return {
            "agent_id": None,
            "entries": [],
            "summary": {"total": 0, "by_category": {}, "by_phase": {}},
        }
    entries = payload.get("entries", [])
    summary = payload.get("summary") or summarize_entries(
        [ToolTraceEntry(**item) for item in entries]
    )
    return {
        "agent_id": payload.get("agent_id"),
        "entries": entries,
        "summary": summary,
    }


def write_mock_tool_trace(run_id: str, llm: str, *, phase: ToolTracePhase) -> None:
    """Deterministic trace rows for mock provider demos."""
    now = datetime.now(timezone.utc).isoformat()
    collector = ToolTraceCollector(run_id, llm, agent_id="mock-agent-id")
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
