"""Bounded Case scheduling on top of isolated Workflow executions."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any

from execution.batch_execution_history import BatchExecutionHistoryRepository
from execution.batch_execution_store import (
    BatchExecutionError,
    BatchExecutionStore,
    summarize_case_runs,
)
from execution.case_evaluator import EvaluationRule, evaluate_case
from execution.workflow_execution import WorkflowExecutionManager
from execution.workflow_execution_store import utc_execution_time


logger = logging.getLogger(__name__)


class BatchScheduler:
    """Run Cases independently while preserving graceful stop and recovery."""

    def __init__(
        self,
        store: BatchExecutionStore,
        workflow_manager: WorkflowExecutionManager,
        history_repository: BatchExecutionHistoryRepository | None = None,
        batch_inputs: Any | None = None,
        *,
        max_total_case_concurrency: int = 16,
    ):
        self.store = store
        self.workflow_manager = workflow_manager
        self.history_repository = history_repository
        self.batch_inputs = batch_inputs
        self.store.recover_incomplete()
        self._global_slots = threading.Semaphore(max_total_case_concurrency)
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._active_executions: dict[str, set[str]] = {}
        self._case_events: dict[tuple[str, str], threading.Event] = {}
        self._case_threads: dict[tuple[str, str], threading.Thread] = {}
        self._case_slots: dict[str, threading.Semaphore] = {}
        self._single_case_previous_status: dict[str, str] = {}
        self._lock = threading.RLock()
        self._closed = False

    def start(self, batch_id: str, *, mode: str = "FULL") -> dict[str, Any]:
        mode = str(mode).upper()
        if mode == "RESUME":
            return self.resume(batch_id)
        if mode == "RETRY_FAILED":
            return self.resume(batch_id, retry_failed=True)
        if mode not in {"FULL", "__PREPARED"}:
            raise BatchExecutionError("不支持的批跑模式")
        prepare_full = mode == "FULL"
        with self._lock:
            if self._closed:
                raise BatchExecutionError("Batch Scheduler 已关闭")
            if batch_id in self._threads and self._threads[batch_id].is_alive():
                raise BatchExecutionError("Batch 正在运行")
            if any(key[0] == batch_id for key in self._case_events):
                raise BatchExecutionError("单条用例正在执行，请等待完成后再启动任务")
            batch = self.store.get(batch_id)
            if batch is None:
                raise BatchExecutionError(f"Batch Execution 不存在: {batch_id}")
            if batch["status"] in {"RUNNING", "STOPPING"}:
                raise BatchExecutionError("旧任务仍在运行，请先停止并等待任务结束")
            if prepare_full and self.batch_inputs is not None:
                if self.store.has_execution(batch) and self.history_repository is not None:
                    now = utc_execution_time()
                    self.history_repository.record(
                        batch,
                        started_at=str(batch.get("started_at") or now),
                        finished_at=str(batch.get("finished_at") or now),
                        deduplicate=True,
                    )
                batch = self.batch_inputs.prepare_execution(batch_id)
            elif batch["status"] != "QUEUED":
                raise BatchExecutionError("只有待执行任务可以启动")
            event = threading.Event()
            attempt_started_at = utc_execution_time()
            batch.update(
                {
                    "status": "RUNNING",
                    "execution_mode": "BATCH",
                    "started_at": batch.get("started_at") or attempt_started_at,
                    "finished_at": None,
                    "error": None,
                }
            )
            self.store.write_batch(batch)
            thread = threading.Thread(
                target=self._run,
                args=(batch_id, event, attempt_started_at),
                daemon=True,
                name=f"batch-{batch_id}",
            )
            self._cancel_events[batch_id] = event
            self._active_executions[batch_id] = set()
            self._threads[batch_id] = thread
            thread.start()
        return deepcopy(batch)

    def resume(self, batch_id: str, *, retry_failed: bool = False) -> dict[str, Any]:
        with self._lock:
            if batch_id in self._threads and self._threads[batch_id].is_alive():
                raise BatchExecutionError("Batch 正在运行")
            if any(key[0] == batch_id for key in self._case_events):
                raise BatchExecutionError("单条用例正在执行，请等待完成后再继续任务")
            batch = self.store.get(batch_id)
            if batch is None:
                raise BatchExecutionError(f"Batch Execution 不存在: {batch_id}")
            eligible = {"INTERRUPTED", "QUEUED"} | (
                {"FAILED"} if retry_failed else set()
            )
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
                raise BatchExecutionError(
                    "没有未执行的用例；重跑失败用例时请启用 retry_failed"
                )
            batch["status"] = "QUEUED"
            batch["finished_at"] = None
            batch["error"] = None
            self._update_summary(batch)
            self.store.write_batch(batch)
            return self.start(batch_id, mode="__PREPARED")

    def cancel(self, batch_id: str) -> bool:
        with self._lock:
            batch = self.store.get(batch_id)
            if batch is None or batch.get("status") != "RUNNING":
                return False
            if batch.get("execution_mode") == "SINGLE_CASE":
                events = [
                    event
                    for (active_batch_id, _case_id), event in self._case_events.items()
                    if active_batch_id == batch_id and not event.is_set()
                ]
            else:
                event = self._cancel_events.get(batch_id)
                events = [] if event is None or event.is_set() else [event]
            if not events:
                return False
            for event in events:
                event.set()
            execution_ids = list(self._active_executions.get(batch_id, set()))
            batch["status"] = "STOPPING"
            batch["finished_at"] = None
            self.store.write_batch(batch)
        for execution_id in execution_ids:
            self.workflow_manager.cancel(execution_id)
        return True

    def start_case(self, batch_id: str, case_run_id: str) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise BatchExecutionError("Batch Scheduler 已关闭")
            batch = self.store.get(batch_id)
            case = self.store.get_case(batch_id, case_run_id)
            if batch is None or case is None:
                raise BatchExecutionError("Batch 或 Case 不存在")
            if batch_id in self._threads and self._threads[batch_id].is_alive():
                raise BatchExecutionError("任务正在运行")
            key = (batch_id, case_run_id)
            has_active_cases = any(item[0] == batch_id for item in self._case_events)
            if batch.get("status") == "STOPPING":
                raise BatchExecutionError("任务正在停止，请等待结束后再启动用例")
            if batch.get("status") == "RUNNING" and (
                batch.get("execution_mode") != "SINGLE_CASE" or not has_active_cases
            ):
                raise BatchExecutionError("任务活动期间不支持单条启动")
            if key in self._case_events or case.get("execution_status") in {
                "QUEUED",
                "RUNNING",
            }:
                raise BatchExecutionError("该用例正在排队或执行，请勿重复启动")

            if not has_active_cases:
                self._single_case_previous_status[batch_id] = batch.get(
                    "status", "QUEUED"
                )
                self._case_slots[batch_id] = threading.Semaphore(
                    max(1, int(batch.get("case_concurrency", 1)))
                )
                self._active_executions[batch_id] = set()
                group_started_at = utc_execution_time()
            else:
                group_started_at = batch.get("started_at") or utc_execution_time()

            event = threading.Event()
            self._case_events[key] = event
            case.update(
                {
                    "status": "QUEUED",
                    "execution_status": "QUEUED",
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "verdict": "NOT_EVALUATED",
                    "evaluation": {"verdict": "NOT_EVALUATED", "rules": []},
                }
            )
            self.store.write_case(case)
            batch.update(
                {
                    "status": "RUNNING",
                    "execution_mode": "SINGLE_CASE",
                    "started_at": group_started_at,
                    "finished_at": None,
                    "error": None,
                }
            )
            self._update_summary(batch)
            self.store.write_batch(batch)
            thread = threading.Thread(
                target=self._run_single_case,
                args=(batch, case, event, self._case_slots[batch_id]),
                daemon=True,
                name=f"single-case-{case_run_id}",
            )
            self._case_threads[key] = thread
            thread.start()
        return case

    def _run_single_case(
        self,
        batch: dict[str, Any],
        case: dict[str, Any],
        event: threading.Event,
        slots: threading.Semaphore,
    ) -> None:
        acquired = False
        try:
            while not event.is_set():
                if slots.acquire(timeout=0.1):
                    acquired = True
                    break
            if acquired and not event.is_set():
                self._run_case(batch, case, event)
            if event.is_set():
                latest_case = self.store.get_case(batch["id"], case["id"])
                if latest_case and latest_case.get("execution_status") == "QUEUED":
                    latest_case.update(
                        {
                            "status": "INTERRUPTED",
                            "execution_status": "INTERRUPTED",
                            "finished_at": utc_execution_time(),
                            "error": {
                                "code": "USER_INTERRUPTED",
                                "message": "用户停止任务",
                                "details": None,
                            },
                        }
                    )
                    self.store.write_case(latest_case)
        finally:
            if acquired:
                slots.release()
            with self._lock:
                key = (batch["id"], case["id"])
                self._case_events.pop(key, None)
                self._case_threads.pop(key, None)
                has_active_case = any(key[0] == batch["id"] for key in self._case_events)
                if not has_active_case:
                    self._active_executions.pop(batch["id"], None)
                    self._case_slots.pop(batch["id"], None)
                    previous_status = self._single_case_previous_status.pop(
                        batch["id"], "QUEUED"
                    )
                else:
                    previous_status = self._single_case_previous_status.get(
                        batch["id"], "QUEUED"
                    )
                latest = self.store.get(batch["id"])
                if latest is not None:
                    self._update_summary(latest)
                    queued_cases = latest["summary"].get("queued", 0)
                    if has_active_case:
                        latest["status"] = "RUNNING"
                        latest["execution_mode"] = "SINGLE_CASE"
                        latest["finished_at"] = None
                    elif queued_cases:
                        latest["status"] = (
                            "STOPPED" if previous_status == "STOPPED" else "QUEUED"
                        )
                        latest["execution_mode"] = None
                        latest["finished_at"] = utc_execution_time()
                    else:
                        latest["status"] = self._completed_status(latest)
                        latest["execution_mode"] = None
                        latest["finished_at"] = utc_execution_time()
                    self.store.write_batch(latest)

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        deadline = time.monotonic() + max(0, wait_seconds)
        with self._lock:
            self._closed = True
            batch_ids = list(self._cancel_events)
            case_events = list(self._case_events.values())
            threads = list(self._threads.values()) + list(self._case_threads.values())
        for batch_id in batch_ids:
            self.cancel(batch_id)
        for event in case_events:
            event.set()
        with self._lock:
            execution_ids = [
                execution_id
                for active in self._active_executions.values()
                for execution_id in active
            ]
        for execution_id in execution_ids:
            self.workflow_manager.cancel(execution_id)
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise BatchExecutionError("Batch Scheduler 未能及时终止")

    def _run(
        self, batch_id: str, cancel_event: threading.Event, attempt_started_at: str
    ) -> None:
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
            latest["status"] = (
                "STOPPED"
                if cancel_event.is_set() and latest["summary"].get("queued", 0)
                else self._completed_status(latest)
            )
            latest["execution_mode"] = None
            latest["finished_at"] = utc_execution_time()
            self._update_summary(latest)
            self.store.write_batch(latest)
            self._record_terminal_history(latest, attempt_started_at)
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
            with self._lock:
                if cancel_event.is_set():
                    return
                latest_case = self.store.get_case(batch["id"], case["id"])
                if latest_case is None or latest_case.get("status") == "RUNNING":
                    return
                case = latest_case
                case["started_at"] = utc_execution_time()
                case.update(
                    {
                        "status": "RUNNING",
                        "execution_status": "RUNNING",
                        "finished_at": None,
                        "error": None,
                        "verdict": "NOT_EVALUATED",
                        "evaluation": {"verdict": "NOT_EVALUATED", "rules": []},
                    }
                )
                self.store.write_case(case)
                latest_batch = self.store.get(batch["id"])
                if latest_batch is not None:
                    self._update_summary(latest_batch)
                    self.store.write_batch(latest_batch)
            max_attempts = 1 + int(batch.get("failure_retry_count", 0))
            for _attempt in range(max_attempts):
                if cancel_event.is_set():
                    case.update(
                        {
                            "status": "INTERRUPTED",
                            "execution_status": "INTERRUPTED",
                            "error": {
                                "code": "USER_INTERRUPTED",
                                "message": "用户停止任务",
                                "details": None,
                            },
                        }
                    )
                    break
                if _attempt:
                    case.update(
                        {
                            "status": "RUNNING",
                            "execution_status": "RUNNING",
                            "finished_at": None,
                            "error": None,
                            "verdict": "NOT_EVALUATED",
                            "evaluation": {"verdict": "NOT_EVALUATED", "rules": []},
                        }
                    )
                    self.store.write_case(case)
                try:
                    self._run_case_attempt(batch, case, cancel_event)
                except Exception as exc:  # noqa: BLE001 - retry isolated Case system errors
                    case["status"] = "FAILED"
                    case["execution_status"] = "FAILED"
                    case["error"] = {
                        "code": "CASE_EXECUTION_FAILED",
                        "message": str(exc),
                        "details": None,
                    }
                if cancel_event.is_set() and case["status"] == "FAILED":
                    case.update(
                        {
                            "status": "INTERRUPTED",
                            "execution_status": "INTERRUPTED",
                            "error": {
                                "code": "USER_INTERRUPTED",
                                "message": "用户停止任务",
                                "details": None,
                            },
                        }
                    )
                    break
                if case["status"] != "FAILED":
                    break
        finally:
            if case["status"] != "QUEUED":
                case["finished_at"] = utc_execution_time()
                self.store.write_case(case)
            if acquired:
                self._global_slots.release()

    def _run_case_attempt(
        self,
        batch: dict[str, Any],
        case: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
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
        deadline = time.monotonic() + self._workflow_poll_timeout_seconds(batch)
        try:
            while True:
                if cancel_event.is_set():
                    self.workflow_manager.cancel(started["id"])
                execution = self.workflow_manager.store.get_workflow(
                    started["workflow_id"], started["id"]
                )
                if execution and execution["status"] in {
                    "SUCCESS", "FAILED", "INTERRUPTED"
                }:
                    break
                if execution is None:
                    raise BatchExecutionError("Workflow Execution 事实丢失")
                if not self.workflow_manager.is_active(started["id"]):
                    raise BatchExecutionError("Workflow 执行线程已结束但未产生终态")
                if time.monotonic() >= deadline:
                    self.workflow_manager.cancel(started["id"])
                    raise BatchExecutionError("Workflow Execution 等待超过配置上界")
                cancel_event.wait(0.03)
        finally:
            with self._lock:
                self._active_executions[batch["id"]].discard(started["id"])
        status = execution["status"]
        case["status"] = status if status in {"SUCCESS", "INTERRUPTED"} else "FAILED"
        case["execution_status"] = case["status"]
        case["error"] = execution.get("error")
        rules = [
            EvaluationRule.model_validate(item)
            for item in batch.get("evaluation_rules", [])
        ]
        if status == "SUCCESS" and rules:
            evaluation = evaluate_case(
                execution.get("context", {}).get("final", {}), rules
            )
            case["evaluation"] = evaluation
            case["verdict"] = evaluation["verdict"]
            if evaluation["verdict"] != "PASS":
                case["status"] = "FAILED"

    @staticmethod
    def _workflow_poll_timeout_seconds(batch: dict[str, Any]) -> float:
        """由冻结节点策略推导 Case 等待上界，并留出 Worker 收敛余量。"""

        snapshot = batch.get("workflow", {}).get("structural_snapshot", {})
        total = 0.0
        for item in snapshot.get("nodes", []):
            node = item.get("node", {}) if isinstance(item, dict) else {}
            execution = node.get("execution") if isinstance(node, dict) else None
            if not isinstance(execution, dict):
                continue
            retries = max(0, int(execution.get("max_attempts", 0)))
            attempts = retries + 1
            total += max(0.0, float(execution.get("delay_seconds", 0)))
            total += attempts * max(0.001, float(execution.get("timeout_seconds", 600)))
            total += retries * max(
                0.0, float(execution.get("retry_interval_seconds", 0))
            )
            total += attempts * 2.0
        return max(30.0, total + 30.0)

    def _record_terminal_history(
        self, batch: dict[str, Any], attempt_started_at: str
    ) -> None:
        if (
            self.history_repository is None
            or batch.get("status") not in {"SUCCESS", "COMPLETED_WITH_ERRORS", "STOPPED"}
        ):
            return
        try:
            self.history_repository.record(batch, started_at=attempt_started_at)
        except Exception:  # noqa: BLE001 - history failure must not rewrite terminal execution fact
            logger.exception("保存任务执行历史失败: %s", batch.get("id"))

    def _update_summary(self, batch: dict[str, Any]) -> None:
        batch["summary"] = summarize_case_runs(self.store.list_cases(batch["id"]))

    @staticmethod
    def _completed_status(batch: dict[str, Any]) -> str:
        summary = batch.get("summary", {})
        return (
            "SUCCESS"
            if summary.get("success", 0) == batch.get("total_cases", 0)
            else "COMPLETED_WITH_ERRORS"
        )
