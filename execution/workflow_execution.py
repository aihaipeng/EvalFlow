"""Cancellable DAG scheduling with compatibility exports for execution APIs."""

from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from typing import Any
from uuid import uuid4

from execution.model_providers import ModelProviderRepository
from execution.workflow_execution_control import ExecutionController
from execution.workflow_execution_store import (
    DEFAULT_EXECUTION_ROOT,
    TERMINAL_NODE_STATUSES,
    TERMINAL_WORKFLOW_STATUSES,
    WorkflowExecutionError,
    WorkflowExecutionStore,
    execution_error as _error,
    local_execution_time,
    seconds_to_milliseconds,
    utc_execution_time,
)
from execution.workflow_node_executor import WorkflowNodeExecutor
from execution.workflow_execution_snapshot import record_from_snapshot, snapshot_record
from execution.workflow_node_tests import NodeTestManager
from execution.workflow_structural_models import (
    WorkflowStructuralRecord,
    WorkflowStructuralRepository,
    validate_workflow_graph,
)
from execution.workflow_values import (
    WorkflowValueError,
    strict_json_clone,
)
from execution.tool_runtime import stream_tool_worker


# Private compatibility alias retained for focused controller tests.
_ExecutionController = ExecutionController


class WorkflowExecutionManager:
    """创建并调度并发 DAG Execution，同时提供查询和全局中断。"""

    def __init__(
        self,
        structural_repository: WorkflowStructuralRepository,
        model_repository: ModelProviderRepository,
        store: WorkflowExecutionStore,
    ):
        self.structural_repository = structural_repository
        self.model_repository = model_repository
        self.store = store
        self.store.recover_incomplete()
        self.node_executor = WorkflowNodeExecutor(
            model_repository,
            store,
            stream_tool_worker,
        )
        self._controllers: dict[str, _ExecutionController] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._execution_workflows: dict[str, str] = {}
        self._lock = threading.Lock()
        self._closed = False

    def start(self, workflow_id: str) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise WorkflowExecutionError("Workflow Execution Manager 已关闭")
        record = self.structural_repository.get(workflow_id)
        if record is None:
            raise WorkflowExecutionError(f"Workflow 不存在: {workflow_id}")
        return self._start_record(record, {"type": "MANUAL"})

    def start_batch(
        self,
        structural_snapshot: dict[str, Any],
        initial_context: dict[str, Any],
        trigger: dict[str, Any],
    ) -> dict[str, Any]:
        """使用 Batch 创建时冻结的结构和当前 Case 输入启动一次执行。"""

        if trigger.get("type") != "BATCH":
            raise WorkflowExecutionError("批量 Workflow trigger.type 必须为 BATCH")
        required = {"batch_execution_id", "case_run_id", "case_id", "row_number"}
        if not required.issubset(trigger):
            raise WorkflowExecutionError("批量 Workflow trigger 缺少 Case 追踪字段")
        return self._start_record(
            record_from_snapshot(structural_snapshot),
            strict_json_clone(trigger),
            initial_context=initial_context,
        )

    def _start_record(
        self,
        record: WorkflowStructuralRecord,
        trigger: dict[str, Any],
        *,
        initial_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise WorkflowExecutionError("Workflow Execution Manager 已关闭")
        external_requirements = validate_workflow_graph(
            record.workflow,
            record.node_models,
        )
        initial = strict_json_clone(
            {} if initial_context is None else initial_context
        )
        if not isinstance(initial, dict):
            raise WorkflowExecutionError("Workflow 初始 Context 必须是 JSON object")
        if trigger.get("type") == "BATCH":
            missing = sorted(set(external_requirements) - set(initial))
            if missing:
                raise WorkflowExecutionError(
                    "任务变量未声明 Workflow 所需的外部 Context 变量: "
                    + ", ".join(missing)
                )
            invalid_nested = sorted(
                name
                for name, paths in external_requirements.items()
                if any(path != name for path in paths)
                and not isinstance(initial[name], (dict, list))
            )
            if invalid_nested:
                raise WorkflowExecutionError(
                    "外部 Context 嵌套引用要求任务变量值为 object 或 array: "
                    + ", ".join(invalid_nested)
                )
        execution_id = str(uuid4())
        snapshot = snapshot_record(record)
        document = {
            "id": execution_id,
            "workflow_id": record.workflow.id,
            "trigger": trigger,
            "status": "PENDING",
            "structural_snapshot": snapshot,
            "created_at": utc_execution_time(),
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "context": {
                "initial": initial,
                "commits": [],
                "final": strict_json_clone(initial),
            },
            "result": {},
            "nodes": [
                {"node_id": node.id, "node_execution_id": None, "state": "WAITING", "reason": None}
                for node in record.node_models
            ],
            "error": None,
        }
        controller = _ExecutionController()
        thread = threading.Thread(
            target=self._run,
            args=(record, document, controller),
            daemon=True,
            name=f"workflow-{execution_id}",
        )
        with self._lock:
            if self._closed:
                raise WorkflowExecutionError("Workflow Execution Manager 已关闭")
            self.store.create(document)
            self._controllers[execution_id] = controller
            self._threads[execution_id] = thread
            self._execution_workflows[execution_id] = record.workflow.id
            thread.start()
        return deepcopy(document)

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        """拒绝新执行，中断全部活动执行并等待线程收敛。"""

        deadline = time.monotonic() + max(0, wait_seconds)
        with self._lock:
            self._closed = True
            controllers = list(self._controllers.values())
            threads = list(self._threads.items())
        for controller in controllers:
            controller.user_cancel.set()
            controller.interrupt_workers()
        for _execution_id, thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        active = [execution_id for execution_id, thread in threads if thread.is_alive()]
        if active:
            raise WorkflowExecutionError(
                f"Workflow Execution 未能及时终止: {', '.join(active)}"
            )

    def cancel(self, execution_id: str) -> bool:
        with self._lock:
            controller = self._controllers.get(execution_id)
        if controller is None:
            return False
        controller.user_cancel.set()
        controller.interrupt_workers()
        return True

    def is_active(self, execution_id: str) -> bool:
        with self._lock:
            thread = self._threads.get(execution_id)
        return bool(thread and thread.is_alive())

    def has_active_workflow(self, workflow_id: str) -> bool:
        """判断指定 Workflow 是否仍有本进程管理的活动 Execution。"""

        with self._lock:
            return any(
                active_workflow_id == workflow_id
                and execution_id in self._threads
                and self._threads[execution_id].is_alive()
                for execution_id, active_workflow_id in self._execution_workflows.items()
            )

    def _run(
        self,
        record: WorkflowStructuralRecord,
        workflow: dict[str, Any],
        controller: _ExecutionController,
    ) -> None:
        started_clock = time.monotonic()
        workflow["status"] = "RUNNING"
        workflow["started_at"] = utc_execution_time()
        self.store.write_workflow(workflow)
        nodes = {node.id: node for node in record.node_models}
        parents = {node_id: set() for node_id in nodes}
        for edge in record.workflow.edges:
            parents[edge.target_node_id].add(edge.source_node_id)
        completed: dict[str, str] = {}
        context: dict[str, Any] = strict_json_clone(
            workflow.get("context", {}).get("initial", {})
        )
        context_lock = threading.Lock()

        def commit(node_id: str, node_execution_id: str, values: dict[str, Any]) -> None:
            if not values:
                return
            with context_lock:
                duplicate = next((name for name in values if name in context), None)
                if duplicate:
                    raise WorkflowValueError(f"Context 变量已存在: {duplicate}")
                cloned = strict_json_clone(values)
                context.update(cloned)
                workflow["context"]["commits"].append(
                    {
                        "sequence": len(workflow["context"]["commits"]) + 1,
                        "node_id": node_id,
                        "node_execution_id": node_execution_id,
                        "committed_at": utc_execution_time(),
                        "values": cloned,
                    }
                )
                workflow["context"]["final"] = strict_json_clone(context)

        try:
            while len(completed) < len(nodes):
                if controller.user_cancel.is_set():
                    break
                ready = [
                    node_id
                    for node_id in nodes
                    if node_id not in completed
                    and self._workflow_node(workflow, node_id)["state"] == "WAITING"
                    and all(completed.get(parent) == "SUCCESS" for parent in parents[node_id])
                ]
                if not ready:
                    break
                with ThreadPoolExecutor(max_workers=max(1, len(ready))) as pool:
                    futures = {
                        pool.submit(
                            self.node_executor.execute,
                            workflow,
                            nodes[node_id],
                            strict_json_clone(context),
                            controller,
                            commit,
                        ): node_id
                        for node_id in ready
                    }
                    pending = set(futures)
                    while pending:
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            node_id = futures[future]
                            try:
                                status, node_execution_id = future.result()
                            except Exception as exc:  # noqa: BLE001
                                status = "FAILED"
                                node_execution_id = None
                                if workflow["error"] is None:
                                    workflow["error"] = _error(
                                        "NODE_FAILED", str(exc), {"node_id": node_id}
                                    )
                            completed[node_id] = status
                            entry = self._workflow_node(workflow, node_id)
                            entry.update(
                                {
                                    "node_execution_id": node_execution_id,
                                    "state": "FINISHED",
                                    "reason": None,
                                }
                            )
                            self.store.write_workflow(workflow)
                            if status in {"FAILED", "TIMEOUT"}:
                                controller.fail_fast.set()
                                controller.interrupt_workers()
                                if workflow["error"] is None:
                                    workflow["error"] = _error(
                                        "NODE_FAILED",
                                        f"节点执行失败: {nodes[node_id].name}",
                                        {
                                            "node_id": node_id,
                                            "node_execution_id": node_execution_id,
                                        },
                                    )
                    if controller.fail_fast.is_set():
                        break

            if controller.user_cancel.is_set():
                status = "INTERRUPTED"
                workflow["error"] = _error("USER_INTERRUPTED", "用户中断 Workflow")
                not_started_reason = "GLOBAL_INTERRUPTED"
            elif controller.fail_fast.is_set() or any(
                status in {"FAILED", "TIMEOUT"} for status in completed.values()
            ):
                status = "FAILED"
                not_started_reason = "WORKFLOW_FAILED"
            else:
                end_node = next(node for node in record.node_models if node.type == "END")
                status = "SUCCESS" if completed.get(end_node.id) == "SUCCESS" else "FAILED"
                not_started_reason = "WORKFLOW_FAILED"
                if status == "FAILED" and workflow["error"] is None:
                    workflow["error"] = _error("NODE_FAILED", "Workflow 未到达 END SUCCESS")
            for entry in workflow["nodes"]:
                if entry["state"] == "WAITING":
                    entry.update({"state": "NOT_STARTED", "reason": not_started_reason})
            workflow["status"] = status
        except (OSError, WorkflowExecutionError) as exc:
            workflow["status"] = "FAILED"
            workflow["error"] = _error("PERSISTENCE_FAILED", str(exc))
        except Exception as exc:  # noqa: BLE001
            workflow["status"] = "FAILED"
            workflow["error"] = _error(
                "NODE_FAILED",
                f"Workflow 调度失败: {exc}",
                {
                    "node_id": None,
                    "node_execution_id": None,
                    "phase": "SCHEDULER",
                    "error_type": type(exc).__name__,
                },
            )
        finally:
            workflow["finished_at"] = utc_execution_time()
            workflow["duration_ms"] = max(0, round((time.monotonic() - started_clock) * 1000))
            try:
                self.store.write_workflow(workflow)
            finally:
                with self._lock:
                    self._controllers.pop(workflow["id"], None)
                    self._threads.pop(workflow["id"], None)
                    self._execution_workflows.pop(workflow["id"], None)

    @staticmethod
    def _workflow_node(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
        return next(item for item in workflow["nodes"] if item["node_id"] == node_id)
