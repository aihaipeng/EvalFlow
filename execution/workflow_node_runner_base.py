"""Shared lifecycle services for structural Node runners."""

from __future__ import annotations

import time
from typing import Any, Protocol

from execution.model_providers import ModelProviderRepository
from execution.node_structural_models import NodeStructuralModel
from execution.workflow_execution_store import (
    WorkflowExecutionError,
    execution_error as _error,
    local_execution_time,
    seconds_to_milliseconds,
    utc_execution_time,
)
from execution.workflow_values import strict_json_clone


class ExecutionController(Protocol):
    user_cancel: Any

    def add_worker(self, worker_id: str) -> None: ...

    def remove_worker(self, worker_id: str) -> None: ...

    def interrupted(self) -> bool: ...


class NodeExecutionStore(Protocol):
    def write_workflow(self, document: dict[str, Any]) -> None: ...

    def write_node(self, document: dict[str, Any]) -> None: ...


class NodeRunnerBase:
    def __init__(
        self,
        model_repository: ModelProviderRepository,
        store: NodeExecutionStore,
        stream_worker: Any,
    ):
        self.model_repository = model_repository
        self.store = store
        self.stream_worker = stream_worker

    def _base_node(
        self, workflow: dict[str, Any], node: NodeStructuralModel, node_execution_id: str
    ) -> dict[str, Any]:
        created = utc_execution_time()
        return {
            "workflow_execution_id": workflow["id"],
            "workflow_id": workflow["workflow_id"],
            "node_execution_id": node_execution_id,
            "node_id": node.id,
            "type": node.type,
            "structural_snapshot": node.model_dump(mode="json"),
            "status": "PENDING",
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "attempt_count": 0,
            "inputs": {},
            "outputs": {},
            "transitions": [{"status": "PENDING", "at": created, "reason": None}],
            "error": None,
        }

    def _start_node(self, document: dict[str, Any]) -> float:
        self.store.write_node(document)
        started_clock = time.monotonic()
        document["status"] = "RUNNING"
        document["started_at"] = local_execution_time()
        document["transitions"].append(
            {"status": "RUNNING", "at": utc_execution_time(), "reason": None}
        )
        self.store.write_node(document)
        return started_clock

    @staticmethod
    def _wait_interruptibly(
        controller: _ExecutionController, delay_milliseconds: int
    ) -> bool:
        """等待调度时间，并同时响应用户中断和 Workflow Fail-Fast。"""

        deadline = time.monotonic() + delay_milliseconds / 1000
        while True:
            if controller.interrupted():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return controller.interrupted()
            controller.user_cancel.wait(min(remaining, 0.05))

    def _begin_business_node(
        self,
        document: dict[str, Any],
        node: NodeStructuralModel,
        controller: _ExecutionController,
        on_running=None,
    ) -> float | None:
        """持久化 PENDING、执行唯一首次延迟，并在实际尝试前进入 RUNNING。"""

        self.store.write_node(document)
        delay_milliseconds = seconds_to_milliseconds(node.execution.delay_seconds)
        interrupted = self._wait_interruptibly(controller, delay_milliseconds)
        if interrupted:
            error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
            self._finish_pending_node(document, "INTERRUPTED", error)
            return None
        if on_running is not None:
            on_running()
        return self._start_node(document)

    def _finish_node(
        self,
        document: dict[str, Any],
        status: str,
        started_clock: float,
        *,
        error: dict[str, Any] | None = None,
    ) -> None:
        document["status"] = status
        document["finished_at"] = local_execution_time()
        document["duration_ms"] = max(0, round((time.monotonic() - started_clock) * 1000))
        document["error"] = error
        document["transitions"].append(
            {"status": status, "at": utc_execution_time(), "reason": error["code"] if error else None}
        )

    def _fail_pending_configuration(
        self, document: dict[str, Any], error: dict[str, Any]
    ) -> None:
        """把尚未开始真实尝试的配置错误持久化为 PENDING -> FAILED。"""

        self._finish_pending_node(document, "FAILED", error)

    def _finish_pending_node(
        self,
        document: dict[str, Any],
        status: str,
        error: dict[str, Any],
    ) -> None:
        """在真实尝试开始前终结节点，不伪造 started_at 或 duration_ms。"""

        self.store.write_node(document)
        document["status"] = status
        document["finished_at"] = local_execution_time()
        document["error"] = error
        document["transitions"].append(
            {"status": status, "at": utc_execution_time(), "reason": error["code"]}
        )
        self.store.write_node(document)

    @staticmethod
    def _missing_configuration_error(
        code: str,
        node_name: str,
        message: str,
        missing_fields: list[str],
        suggestion: str,
    ) -> dict[str, Any]:
        return _error(
            code,
            f"节点“{node_name}”{message}",
            {"missing_fields": missing_fields, "suggestion": suggestion},
        )

    def execute_start(self, workflow, node, node_execution_id, context):
        document = self._base_node(workflow, node, node_execution_id)
        document["logs"] = {
            "input_validation": {"status": "NOT_STARTED", "inputs": {}, "error": None},
            "context_commit": {"status": "NOT_STARTED", "outputs": {}, "error": None},
        }
        started = self._start_node(document)
        document["attempt_count"] = 1
        inputs = {item.name: strict_json_clone(item.value) for item in node.inputs}
        document["inputs"] = inputs
        document["logs"]["input_validation"] = {
            "status": "SUCCESS", "inputs": strict_json_clone(inputs), "error": None
        }
        document["outputs"] = strict_json_clone(inputs)
        document["logs"]["context_commit"] = {
            "status": "SUCCESS", "outputs": strict_json_clone(inputs), "error": None
        }
        self._finish_node(document, "SUCCESS", started)
        return document, inputs

    def execute_end(self, workflow, node, node_execution_id, context):
        document = self._base_node(workflow, node, node_execution_id)
        started = self._start_node(document)
        document["attempt_count"] = 1
        self._finish_node(document, "SUCCESS", started)
        return document, {}
