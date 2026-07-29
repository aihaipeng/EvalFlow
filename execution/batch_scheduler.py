"""Bounded Case scheduling on top of isolated Workflow executions."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore
from execution.case_evaluator import EvaluationRule, evaluate_case
from execution.workflow_execution import WorkflowExecutionManager
from execution.workflow_execution_store import utc_execution_time


class BatchScheduler:
    """Run Cases independently while preserving Batch cancellation and recovery."""

    def __init__(
        self,
        store: BatchExecutionStore,
        workflow_manager: WorkflowExecutionManager,
        *,
        max_total_case_concurrency: int = 16,
    ):
        self.store = store
        self.workflow_manager = workflow_manager
        self.store.recover_incomplete()
        self._global_slots = threading.Semaphore(max_total_case_concurrency)
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._active_executions: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        self._closed = False

    def start(self, batch_id: str) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise BatchExecutionError("Batch Scheduler 已关闭")
            if batch_id in self._threads and self._threads[batch_id].is_alive():
                raise BatchExecutionError("Batch 正在运行")
        batch = self.store.get(batch_id)
        if batch is None:
            raise BatchExecutionError(f"Batch Execution 不存在: {batch_id}")
        if batch["status"] != "QUEUED":
            raise BatchExecutionError("只有 QUEUED Batch 可以启动")
        event = threading.Event()
        batch.update(
            {
                "status": "RUNNING",
                "started_at": batch.get("started_at") or utc_execution_time(),
                "finished_at": None,
                "error": None,
            }
        )
        self.store.write_batch(batch)
        thread = threading.Thread(
            target=self._run,
            args=(batch_id, event),
            daemon=True,
            name=f"batch-{batch_id}",
        )
        with self._lock:
            self._cancel_events[batch_id] = event
            self._active_executions[batch_id] = set()
            self._threads[batch_id] = thread
            thread.start()
        return deepcopy(batch)

    def resume(self, batch_id: str, *, retry_failed: bool = False) -> dict[str, Any]:
        with self._lock:
            if batch_id in self._threads and self._threads[batch_id].is_alive():
                raise BatchExecutionError("Batch 正在运行")
        batch = self.store.get(batch_id)
        if batch is None:
            raise BatchExecutionError(f"Batch Execution 不存在: {batch_id}")
        eligible = {"INTERRUPTED", "QUEUED"} | ({"FAILED"} if retry_failed else set())
        reset = 0
        for case in self.store.list_cases(batch_id):
            if case["status"] not in eligible:
                continue
            case.update(
                {
                    "status": "QUEUED",
                    "execution_status": "NOT_STARTED",
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "verdict": "NOT_EVALUATED",
                    "evaluation": {"verdict": "NOT_EVALUATED", "rules": []},
                }
            )
            self.store.write_case(case)
            reset += 1
        if not reset:
            raise BatchExecutionError("没有可恢复的 Case；重跑失败 Case 时请启用 retry_failed")
        batch["status"] = "QUEUED"
        batch["finished_at"] = None
        batch["error"] = None
        self._update_summary(batch)
        self.store.write_batch(batch)
        return self.start(batch_id)

    def cancel(self, batch_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(batch_id)
            execution_ids = list(self._active_executions.get(batch_id, set()))
        if event is None:
            return False
        event.set()
        for execution_id in execution_ids:
            self.workflow_manager.cancel(execution_id)
        return True

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        deadline = time.monotonic() + max(0, wait_seconds)
        with self._lock:
            self._closed = True
            batch_ids = list(self._cancel_events)
            threads = list(self._threads.values())
        for batch_id in batch_ids:
            self.cancel(batch_id)
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise BatchExecutionError("Batch Scheduler 未能及时终止")

    def _run(self, batch_id: str, cancel_event: threading.Event) -> None:
        batch = self.store.get(batch_id)
        queued = [case for case in self.store.list_cases(batch_id) if case["status"] == "QUEUED"]
        try:
            with ThreadPoolExecutor(
                max_workers=batch["case_concurrency"],
                thread_name_prefix=f"case-{batch_id[:8]}",
            ) as pool:
                futures = [pool.submit(self._run_case, batch, case, cancel_event) for case in queued]
                for future in as_completed(futures):
                    future.result()
                    latest = self.store.get(batch_id)
                    self._update_summary(latest)
                    self.store.write_batch(latest)
            latest = self.store.get(batch_id)
            if cancel_event.is_set():
                for case in self.store.list_cases(batch_id):
                    if case["status"] == "QUEUED":
                        case.update(
                            {
                                "status": "INTERRUPTED",
                                "execution_status": "INTERRUPTED",
                                "finished_at": utc_execution_time(),
                            }
                        )
                        self.store.write_case(case)
                status = "INTERRUPTED"
            else:
                statuses = {case["status"] for case in self.store.list_cases(batch_id)}
                status = "SUCCESS" if statuses == {"SUCCESS"} else "COMPLETED_WITH_ERRORS"
            latest["status"] = status
            latest["finished_at"] = utc_execution_time()
            self._update_summary(latest)
            self.store.write_batch(latest)
        except Exception as exc:  # noqa: BLE001 - preserve a recoverable Batch terminal fact
            latest = self.store.get(batch_id)
            if latest is not None:
                latest["status"] = "INTERRUPTED"
                latest["finished_at"] = utc_execution_time()
                latest["error"] = {
                    "code": "BATCH_SCHEDULER_FAILED",
                    "message": str(exc),
                    "details": None,
                }
                self._update_summary(latest)
                self.store.write_batch(latest)
        finally:
            with self._lock:
                self._cancel_events.pop(batch_id, None)
                self._active_executions.pop(batch_id, None)
                self._threads.pop(batch_id, None)

    def _run_case(
        self, batch: dict[str, Any], case: dict[str, Any], cancel_event: threading.Event
    ) -> None:
        acquired = False
        try:
            while not cancel_event.is_set():
                if self._global_slots.acquire(timeout=0.1):
                    acquired = True
                    break
            if not acquired:
                return
            if cancel_event.is_set():
                return
            case.update(
                {
                    "status": "RUNNING", "execution_status": "RUNNING",
                    "started_at": utc_execution_time(), "error": None,
                    "verdict": "NOT_EVALUATED",
                    "evaluation": {"verdict": "NOT_EVALUATED", "rules": []},
                }
            )
            self.store.write_case(case)
            started = self.workflow_manager.start_batch(
                batch["workflow"]["structural_snapshot"],
                case["start_inputs"],
                {
                    "type": "BATCH",
                    "batch_execution_id": batch["id"],
                    "case_run_id": case["id"],
                    "case_id": case["case_id"],
                    "row_number": case["row_number"],
                },
            )
            case["workflow_execution_ids"].append(started["id"])
            self.store.write_case(case)
            with self._lock:
                self._active_executions[batch["id"]].add(started["id"])
            if cancel_event.is_set():
                self.workflow_manager.cancel(started["id"])
            while True:
                execution = self.workflow_manager.store.get_workflow(
                    started["workflow_id"], started["id"]
                )
                if execution and execution["status"] in {"SUCCESS", "FAILED", "INTERRUPTED"}:
                    break
                time.sleep(0.03)
            with self._lock:
                self._active_executions[batch["id"]].discard(started["id"])
            status = execution["status"]
            case["status"] = status if status in {"SUCCESS", "INTERRUPTED"} else "FAILED"
            case["execution_status"] = case["status"]
            case["error"] = execution.get("error")
            rules = [EvaluationRule.model_validate(item) for item in batch.get("evaluation_rules", [])]
            if status == "SUCCESS" and rules:
                evaluation = evaluate_case(execution.get("context", {}).get("final", {}), rules)
                case["evaluation"] = evaluation
                case["verdict"] = evaluation["verdict"]
                if evaluation["verdict"] != "PASS":
                    case["status"] = "FAILED"
        except Exception as exc:  # noqa: BLE001 - one Case failure must not stop peers
            case["status"] = "FAILED"
            case["execution_status"] = "FAILED"
            case["error"] = {"code": "CASE_EXECUTION_FAILED", "message": str(exc), "details": None}
        finally:
            if case["status"] != "QUEUED":
                case["finished_at"] = utc_execution_time()
                self.store.write_case(case)
            if acquired:
                self._global_slots.release()

    def _update_summary(self, batch: dict[str, Any]) -> None:
        counts = {
            "queued": 0, "running": 0, "success": 0, "failed": 0, "interrupted": 0,
            "pass": 0, "fail": 0, "error": 0, "not_evaluated": 0,
        }
        for case in self.store.list_cases(batch["id"]):
            counts[case["status"].lower()] += 1
            counts[case.get("verdict", "NOT_EVALUATED").lower()] += 1
        batch["summary"] = counts
