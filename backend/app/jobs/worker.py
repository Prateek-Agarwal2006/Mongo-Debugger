from __future__ import annotations

import logging
import time
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.run_workspace import RunWorkspace, get_run_workspace
from backend.app.jobs.pipeline import run_pipeline_job
from backend.app.jobs.queue import FileJobQueue

logger = logging.getLogger(__name__)


class PipelineWorker:
    """Standalone process: poll file queue, claim jobs, run mongo-ftdc pipeline."""

    def __init__(self, workspace_root: Path, *, poll_seconds: float = 2.0) -> None:
        self.workspace = RunWorkspace(workspace_root)
        self.poll_seconds = poll_seconds
        self._queue = FileJobQueue(self.workspace)

    def recover_stale_jobs(self) -> int:
        count = self._queue.requeue_stale_processing()
        if count:
            logger.info("Requeued %d stale processing job(s) after worker startup", count)
        return count

    def process_one(self) -> bool:
        claimed = self._queue.claim_next()
        if claimed is None:
            return False
        input_path = self.workspace.root / claimed.input_path
        try:
            run_pipeline_job(self.workspace.root, claimed.job_id, claimed.run_id, input_path)  # want both job_id and run_id(this is id given when we uploadeded the data) as same run_id may run multiple times so job_id should be unique for each run....
        finally:
            self._queue.complete(claimed.job_id)
        return True

    def run_forever(self) -> None:  # so nothing else calls this function....only this function calls the process_one function....so this function is the main entry point for the worker....and it sleeps for the poll_seconds and then calls the process_one function....and if the process_one function returns False then it sleeps for the poll_seconds again....and if the process_one function returns True then it breaks out of the loop and exits the function....
        self.recover_stale_jobs()
        while True:
            if not self.process_one():
                time.sleep(self.poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    workspace = get_run_workspace()
    worker = PipelineWorker(workspace.root, poll_seconds=settings.pipeline_worker_poll_seconds)
    logger.info("Pipeline worker started (root=%s, poll=%ss)", workspace.root, settings.pipeline_worker_poll_seconds)
    worker.run_forever()


if __name__ == "__main__":
    main()
