from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalBudget:
    """Fallback retrieval budget for Phase 2 LLM tool loops.

    When run_id and llm are set, state syncs through the phase2_state table
    ('budget' key) so the orchestrator and MCP server subprocesses share one
    counter across processes and pods.
    """

    max_tool_calls: int = 12
    tool_calls_used: int = 0
    tool_call_history: list[str] = field(default_factory=list)
    run_id: str | None = field(default=None, repr=False)
    llm: str | None = field(default=None, repr=False)

    def _synced(self) -> bool:
        return bool(self.run_id and self.llm)

    def sync_load(self) -> None:
        if not self._synced():
            return
        from backend.app.simagix.llm.state import load_state

        payload = load_state(self.run_id, self.llm, "budget")
        if payload is None:
            return
        self.max_tool_calls = payload.get("max_tool_calls", self.max_tool_calls)
        self.tool_calls_used = payload.get("tool_calls_used", self.tool_calls_used)
        self.tool_call_history = list(payload.get("tool_call_history", self.tool_call_history))

    def sync_save(self) -> None:
        if not self._synced():
            return
        from backend.app.simagix.llm.state import save_state

        save_state(
            self.run_id,
            self.llm,
            "budget",
            {
                "max_tool_calls": self.max_tool_calls,
                "tool_calls_used": self.tool_calls_used,
                "tool_call_history": self.tool_call_history,
            },
        )

    def consume_tool_call(self, tool_name: str) -> None:
        self.sync_load()
        if self.tool_calls_used >= self.max_tool_calls:
            raise RuntimeError(
                f"Retrieval budget exhausted ({self.max_tool_calls} tool calls). "
                "Stop requesting fallback evidence and finalize RCA with available tier_1 data."
            )
        self.tool_calls_used += 1
        self.tool_call_history.append(tool_name)
        self.sync_save()

    def remaining(self) -> int:
        return max(0, self.max_tool_calls - self.tool_calls_used)

    def status(self) -> dict[str, Any]:
        self.sync_load()
        return {
            "max_tool_calls": self.max_tool_calls,
            "tool_calls_used": self.tool_calls_used,
            "remaining_tool_calls": self.remaining(),
            "tool_call_history": self.tool_call_history,
            "budget_exhausted": self.tool_calls_used >= self.max_tool_calls,
        }
