from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RetrievalBudget:
    """Fallback retrieval budget for Phase 2 LLM tool loops."""

    max_tool_calls: int = 12
    tool_calls_used: int = 0
    tool_call_history: list[str] = field(default_factory=list)
    sync_path: Path | None = field(default=None, repr=False)

    def sync_load(self) -> None:
        if self.sync_path is None or not self.sync_path.exists():
            return
        payload = json.loads(self.sync_path.read_text(encoding="utf-8"))
        self.max_tool_calls = payload.get("max_tool_calls", self.max_tool_calls)
        self.tool_calls_used = payload.get("tool_calls_used", self.tool_calls_used)
        self.tool_call_history = list(payload.get("tool_call_history", self.tool_call_history))

    def sync_save(self) -> None:
        if self.sync_path is None:
            return
        self.sync_path.parent.mkdir(parents=True, exist_ok=True)
        self.sync_path.write_text(
            json.dumps(
                {
                    "max_tool_calls": self.max_tool_calls,
                    "tool_calls_used": self.tool_calls_used,
                    "tool_call_history": self.tool_call_history,
                }
            ),
            encoding="utf-8",
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
