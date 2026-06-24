from __future__ import annotations

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.catalog import hatchet_block_message, hatchet_blocks_phase2


class HatchetNotReadyError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def assert_hatchet_ready_for_phase2(workspace_root, run_id: str) -> None:
    workspace = RunWorkspace(workspace_root)
    if not hatchet_blocks_phase2(workspace, run_id):
        return
    raise HatchetNotReadyError(hatchet_block_message(workspace, run_id))
