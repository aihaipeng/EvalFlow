"""Cancellation state shared by Workflow and transient node executions."""

from __future__ import annotations

import threading

from execution.tool_runtime import interrupt_tool_run


class ExecutionController:
    """Own the stop signals and active Worker ids for one execution."""

    def __init__(self) -> None:
        self.user_cancel = threading.Event()
        self.fail_fast = threading.Event()
        self.worker_ids: set[str] = set()
        self.lock = threading.Lock()

    def add_worker(self, worker_id: str) -> None:
        with self.lock:
            self.worker_ids.add(worker_id)
            interrupted = self.interrupted()
        if interrupted:
            interrupt_tool_run(worker_id)

    def remove_worker(self, worker_id: str) -> None:
        with self.lock:
            self.worker_ids.discard(worker_id)

    def interrupt_workers(self) -> None:
        with self.lock:
            worker_ids = list(self.worker_ids)
        for worker_id in worker_ids:
            interrupt_tool_run(worker_id)

    def interrupted(self) -> bool:
        return self.user_cancel.is_set() or self.fail_fast.is_set()
