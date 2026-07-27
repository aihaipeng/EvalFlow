"""File-backed Workflow/Node Execution models and cancellable DAG scheduler."""

from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

from execution.model_gateway import (
    anthropic_headers,
    anthropic_messages_url,
    build_anthropic_request,
    build_chat_completion_request,
    chat_completions_url,
)
from execution.model_providers import ModelProviderRepository
from execution.node_structural_models import NodeStructuralModel
from execution.workflow_structural_models import (
    WorkflowStructuralRecord,
    WorkflowStructuralRepository,
    WorkflowStructuralRepositoryError,
    validate_workflow_graph,
)
from execution.workflow_values import (
    WorkflowOutputSourceError,
    WorkflowOutputTypeError,
    WorkflowValueError,
    collect_outputs,
    convert_output,
    resolve_template,
    strict_json_clone,
)
from web.tool_runtime import interrupt_tool_run, stream_tool_worker


DEFAULT_EXECUTION_ROOT = Path(__file__).resolve().parents[1] / "run_storage" / "workflow_executions"
TERMINAL_WORKFLOW_STATUSES = {"SUCCESS", "FAILED", "INTERRUPTED"}
TERMINAL_NODE_STATUSES = {"SUCCESS", "FAILED", "TIMEOUT", "INTERRUPTED"}
LOG_LIMIT_BYTES = 5 * 1024 * 1024


def seconds_to_milliseconds(value: float) -> int:
    """把 Structural Model 的秒值统一舍入为执行器使用的整数毫秒。"""

    return max(0, round(value * 1000))


def utc_execution_time() -> str:
    """返回 Workflow Execution 使用的 UTC ISO-8601 毫秒时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_execution_time() -> str:
    """返回 Node Execution 使用的本机 Asia/Shanghai 秒级时间。"""

    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise WorkflowExecutionError(f"{label} 必须是 UUID") from exc
    if parsed.version != 4:
        raise WorkflowExecutionError(f"{label} 必须是 UUIDv4")
    return str(parsed)


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


class WorkflowExecutionError(RuntimeError):
    """Workflow 无法启动、读取、持久化或满足执行状态机时的领域错误。"""


class WorkflowExecutionStore:
    """使用原子 JSON 文件持久化 Workflow 和 Node Execution 客观事实。"""

    def __init__(self, root: str | Path = DEFAULT_EXECUTION_ROOT):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def workflow_root(self, workflow_id: str, *, create: bool = False) -> Path:
        path = self.root / _uuid(workflow_id, "workflow_id")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def execution_root(self, workflow_id: str, execution_id: str, *, create: bool = False) -> Path:
        path = self.workflow_root(workflow_id, create=create) / _uuid(execution_id, "execution_id")
        if create:
            (path / "nodes").mkdir(parents=True, exist_ok=True)
        return path

    def create(self, document: dict[str, Any]) -> None:
        path = self.execution_root(document["workflow_id"], document["id"], create=True)
        target = path / "workflow.json"
        if target.exists():
            raise WorkflowExecutionError(f"Workflow Execution 已存在: {document['id']}")
        with self._write_lock:
            self._atomic_write(target, document)

    def write_workflow(self, document: dict[str, Any]) -> None:
        target = self.execution_root(document["workflow_id"], document["id"]) / "workflow.json"
        if not target.is_file():
            raise WorkflowExecutionError(f"Workflow Execution 不存在: {document['id']}")
        with self._write_lock:
            self._atomic_write(target, document)

    def write_node(self, document: dict[str, Any]) -> None:
        target = (
            self.execution_root(document["workflow_id"], document["workflow_execution_id"], create=True)
            / "nodes"
            / f"{_uuid(document['node_execution_id'], 'node_execution_id')}.json"
        )
        with self._write_lock:
            self._atomic_write(target, document)

    def get_workflow(self, workflow_id: str, execution_id: str) -> dict[str, Any] | None:
        path = self.execution_root(workflow_id, execution_id) / "workflow.json"
        return self._read(path) if path.is_file() else None

    def get_nodes(self, workflow_id: str, execution_id: str) -> list[dict[str, Any]]:
        directory = self.execution_root(workflow_id, execution_id) / "nodes"
        if not directory.is_dir():
            return []
        nodes = [self._read(path) for path in directory.glob("*.json")]
        return sorted(nodes, key=lambda item: (item.get("started_at") or "", item["node_execution_id"]))

    def list(self, workflow_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        root = self.workflow_root(workflow_id)
        if not root.is_dir():
            return []
        documents = []
        for path in root.glob("*/workflow.json"):
            try:
                documents.append(self._read(path))
            except (OSError, json.JSONDecodeError, WorkflowExecutionError):
                continue
        documents.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return documents[:limit]

    def delete_workflow_root(self, workflow_id: str) -> None:
        staged = self.stage_workflow_root_deletion(workflow_id)
        self.finalize_workflow_root_deletion(staged)

    def stage_workflow_root_deletion(self, workflow_id: str) -> Path | None:
        root = self.workflow_root(workflow_id)
        if not root.is_dir():
            return None
        staged = self.root / f".deleting-{_uuid(workflow_id, 'workflow_id')}-{uuid4()}"
        with self._write_lock:
            os.replace(root, staged)
        return staged

    def restore_workflow_root_deletion(self, workflow_id: str, staged: Path | None) -> None:
        if staged is None or not staged.exists():
            return
        root = self.workflow_root(workflow_id)
        with self._write_lock:
            if root.exists():
                raise WorkflowExecutionError(f"Workflow Execution 目录恢复冲突: {workflow_id}")
            os.replace(staged, root)

    def finalize_workflow_root_deletion(self, staged: Path | None) -> None:
        if staged is not None and staged.is_dir():
            shutil.rmtree(staged)

    def recover_incomplete(self) -> int:
        recovered = 0
        for path in self.root.glob("*/*/workflow.json"):
            try:
                workflow = self._read(path)
            except (OSError, json.JSONDecodeError, WorkflowExecutionError):
                continue
            if workflow.get("status") not in {"PENDING", "RUNNING"}:
                continue
            now = utc_execution_time()
            for node_path in path.parent.joinpath("nodes").glob("*.json"):
                node = self._read(node_path)
                if node.get("status") in {"PENDING", "RUNNING"}:
                    node["status"] = "FAILED"
                    node["finished_at"] = local_execution_time()
                    node["error"] = _error("RUNTIME_LOST", "服务重启导致节点运行时丢失")
                    node.setdefault("transitions", []).append(
                        {"status": "FAILED", "at": now, "reason": "RUNTIME_LOST"}
                    )
                    self._atomic_write(node_path, node)
            workflow["status"] = "FAILED"
            workflow["finished_at"] = now
            workflow["error"] = _error("PROCESS_RESTARTED", "服务重启，未完成执行不自动续跑")
            self._atomic_write(path, workflow)
            recovered += 1
        return recovered

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        for attempt in range(6):
            try:
                raw = path.read_text(encoding="utf-8")
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.01)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise WorkflowExecutionError(f"Execution JSON 根必须是 object: {path}")
        return payload

    @staticmethod
    def _atomic_write(path: Path, document: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            strict_json_clone(document), ensure_ascii=False, allow_nan=False, indent=2
        ) + "\n"
        temporary = path.with_name(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(6):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01)
        finally:
            if temporary.exists():
                temporary.unlink()


class _ExecutionController:
    """一个活动 Workflow Execution 的取消信号和 Worker 集合。"""

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
        self._controllers: dict[str, _ExecutionController] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._execution_workflows: dict[str, str] = {}
        self._lock = threading.Lock()

    def start(self, workflow_id: str) -> dict[str, Any]:
        record = self.structural_repository.get(workflow_id)
        if record is None:
            raise WorkflowExecutionError(f"Workflow 不存在: {workflow_id}")
        validate_workflow_graph(record.workflow, record.node_models)
        execution_id = str(uuid4())
        snapshot = self._snapshot(record)
        document = {
            "id": execution_id,
            "workflow_id": workflow_id,
            "trigger": {"type": "MANUAL"},
            "status": "PENDING",
            "structural_snapshot": snapshot,
            "created_at": utc_execution_time(),
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "context": {"commits": [], "final": {}},
            "nodes": [
                {"node_id": node.id, "node_execution_id": None, "state": "WAITING", "reason": None}
                for node in record.node_models
            ],
            "error": None,
        }
        self.store.create(document)
        controller = _ExecutionController()
        thread = threading.Thread(
            target=self._run,
            args=(record, document, controller),
            daemon=True,
            name=f"workflow-{execution_id}",
        )
        with self._lock:
            self._controllers[execution_id] = controller
            self._threads[execution_id] = thread
            self._execution_workflows[execution_id] = workflow_id
        thread.start()
        return deepcopy(document)

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

    @staticmethod
    def _snapshot(record: WorkflowStructuralRecord) -> dict[str, Any]:
        bindings = {binding.node_id: binding for binding in record.workflow.nodes}
        return {
            "workflow": {
                "id": record.workflow.id,
                "name": record.workflow.name,
                "description": record.workflow.description,
            },
            "nodes": [
                {
                    "node": node.model_dump(mode="json"),
                    "position_x": bindings[node.id].position_x,
                    "position_y": bindings[node.id].position_y,
                }
                for node in record.node_models
            ],
            "edges": [edge.model_dump(mode="json") for edge in record.workflow.edges],
        }

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
        context: dict[str, Any] = {}
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
                            self._execute_node,
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
        except Exception as exc:  # noqa: BLE001
            workflow["status"] = "FAILED"
            workflow["error"] = _error("PERSISTENCE_FAILED", str(exc))
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

    def _execute_node(
        self,
        workflow: dict[str, Any],
        node: NodeStructuralModel,
        context: dict[str, Any],
        controller: _ExecutionController,
        commit,
    ) -> tuple[str, str]:
        node_execution_id = str(uuid4())
        entry = self._workflow_node(workflow, node.id)
        initial_state = "PENDING" if node.type in {"SCRIPT", "LLM", "HTTP"} else "RUNNING"
        entry.update(
            {"node_execution_id": node_execution_id, "state": initial_state, "reason": None}
        )
        self.store.write_workflow(workflow)

        def mark_running() -> None:
            entry.update({"state": "RUNNING", "reason": None})
            self.store.write_workflow(workflow)

        if node.type == "START":
            document, outputs = self._execute_start(workflow, node, node_execution_id, context)
        elif node.type == "END":
            document, outputs = self._execute_end(workflow, node, node_execution_id)
        elif node.type == "SCRIPT":
            document, outputs = self._execute_script(
                workflow,
                node,
                node_execution_id,
                context,
                controller,
                on_running=mark_running,
            )
        elif node.type == "LLM":
            document, outputs = self._execute_llm(
                workflow,
                node,
                node_execution_id,
                context,
                controller,
                on_running=mark_running,
            )
        elif node.type == "HTTP":
            document, outputs = self._execute_http(
                workflow,
                node,
                node_execution_id,
                context,
                controller,
                on_running=mark_running,
            )
        else:
            raise WorkflowExecutionError(f"不支持的 Node 类型: {node.type}")
        if document["status"] == "SUCCESS":
            try:
                commit(node.id, node_execution_id, outputs)
            except WorkflowValueError as exc:
                if document["transitions"] and document["transitions"][-1]["status"] == "SUCCESS":
                    document["transitions"].pop()
                document["status"] = "FAILED"
                document["outputs"] = {}
                document["error"] = _error("CONTEXT_KEY_EXISTS", str(exc))
                document["transitions"].append(
                    {"status": "FAILED", "at": utc_execution_time(), "reason": "CONTEXT_KEY_EXISTS"}
                )
                if node.type == "START":
                    document["logs"]["context_commit"] = {
                        "status": "FAILED", "outputs": {}, "error": document["error"]
                    }
            document["finished_at"] = local_execution_time()
        self.store.write_node(document)
        return document["status"], node_execution_id

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

    def _start_node(
        self, document: dict[str, Any], *, lifecycle_started: float | None = None
    ) -> float:
        self.store.write_node(document)
        document["status"] = "RUNNING"
        document["started_at"] = local_execution_time()
        document["transitions"].append(
            {"status": "RUNNING", "at": utc_execution_time(), "reason": None}
        )
        self.store.write_node(document)
        return lifecycle_started if lifecycle_started is not None else time.monotonic()

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

        lifecycle_started = time.monotonic()
        self.store.write_node(document)
        delay_milliseconds = seconds_to_milliseconds(node.execution.delay_seconds)
        interrupted = self._wait_interruptibly(controller, delay_milliseconds)
        if interrupted:
            error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
            self._finish_node(document, "INTERRUPTED", lifecycle_started, error=error)
            self.store.write_node(document)
            return None
        if on_running is not None:
            on_running()
        return self._start_node(document, lifecycle_started=lifecycle_started)

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

        self.store.write_node(document)
        document["status"] = "FAILED"
        document["finished_at"] = local_execution_time()
        document["error"] = error
        document["transitions"].append(
            {"status": "FAILED", "at": utc_execution_time(), "reason": error["code"]}
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

    def _execute_start(self, workflow, node, node_execution_id, context):
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

    def _execute_end(self, workflow, node, node_execution_id):
        document = self._base_node(workflow, node, node_execution_id)
        started = self._start_node(document)
        document["attempt_count"] = 1
        self._finish_node(document, "SUCCESS", started)
        return document, {}

    def _execute_script(
        self, workflow, node, node_execution_id, context, controller, on_running=None
    ):
        document = self._base_node(workflow, node, node_execution_id)
        document["logs"] = {"truncated": False, "captured_bytes": 0, "attempts": []}
        if not node.script.strip():
            error = self._missing_configuration_error(
                "SCRIPT_CONFIGURATION_INCOMPLETE",
                node.name,
                "未填写 Python 代码",
                ["script"],
                "打开节点设置，在 main.py 中填写需要执行的 Python 代码",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        started = self._begin_business_node(document, node, controller, on_running)
        if started is None:
            return document, {}
        final_error = None
        final_status = "FAILED"
        outputs: dict[str, Any] = {}
        for attempt_number in range(1, node.execution.max_attempts + 2):
            if controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
                break
            document["attempt_count"] = attempt_number
            document["inputs"] = strict_json_clone(context)
            attempt = {
                "attempt": attempt_number,
                "status": "RUNNING",
                "console": [],
                "traceback": None,
                "error": None,
            }
            document["logs"]["attempts"].append(attempt)
            self.store.write_node(document)
            sequence = 0

            def on_console(stream: str, text: str) -> None:
                nonlocal sequence
                sequence += 1
                self._append_script_log(document["logs"], attempt, sequence, stream, text)
                self.store.write_node(document)

            controller.add_worker(node_execution_id)
            try:
                result = stream_tool_worker(
                    {
                        "mode": "PYTHON",
                        "code": node.script,
                        "inputs": {},
                        "config": {},
                        "context": strict_json_clone(context),
                        "output_variable_names": [item.source for item in node.outputs],
                    },
                    lambda _text: None,
                    node_execution_id,
                    timeout_seconds=(
                        seconds_to_milliseconds(node.execution.timeout_seconds) / 1000
                    ),
                    on_console=on_console,
                )
            finally:
                controller.remove_worker(node_execution_id)
            if result.get("interrupted") or controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
                attempt.update({"status": final_status, "error": final_error})
                break
            if result.get("timed_out"):
                final_status = "TIMEOUT"
                final_error = _error("SCRIPT_TIMEOUT", "SCRIPT 执行超时")
                attempt.update({"status": final_status, "error": final_error})
            elif not result.get("ok"):
                final_status = "FAILED"
                final_error = _error("SCRIPT_RUNTIME_ERROR", result.get("error") or "SCRIPT 执行失败")
                traceback_text = result.get("traceback")
                if traceback_text:
                    attempt["traceback"] = self._append_log_text(document["logs"], traceback_text)
                attempt.update({"status": final_status, "error": final_error})
            elif result.get("missing_variable_names"):
                missing = result["missing_variable_names"][0]
                final_status = "FAILED"
                final_error = _error(
                    "SCRIPT_OUTPUT_MISSING",
                    f"Python 顶层变量不存在: {missing}",
                    {"source": missing},
                )
                attempt.update({"status": final_status, "error": final_error})
                break
            else:
                try:
                    variables = result.get("python_variables") or {}
                    outputs = {
                        item.name: convert_output(variables[item.source], item.type)
                        for item in node.outputs
                    }
                except (WorkflowValueError, KeyError) as exc:
                    final_status = "FAILED"
                    final_error = _error("SCRIPT_OUTPUT_TYPE_MISMATCH", str(exc))
                    attempt.update({"status": final_status, "error": final_error})
                    break
                attempt.update({"status": "SUCCESS", "error": None})
                final_status = "SUCCESS"
                final_error = None
                break
            if attempt_number <= node.execution.max_attempts:
                if self._wait_interruptibly(
                    controller,
                    seconds_to_milliseconds(node.execution.retry_interval_seconds),
                ):
                    break
        document["outputs"] = strict_json_clone(outputs) if final_status == "SUCCESS" else {}
        self._finish_node(document, final_status, started, error=final_error)
        return document, outputs if final_status == "SUCCESS" else {}

    @staticmethod
    def _append_log_text(logs: dict[str, Any], text: str) -> str:
        remaining = LOG_LIMIT_BYTES - logs["captured_bytes"]
        if remaining <= 0:
            logs["truncated"] = True
            return ""
        encoded = text.encode("utf-8")
        kept = encoded[:remaining]
        while True:
            try:
                result = kept.decode("utf-8")
                break
            except UnicodeDecodeError:
                kept = kept[:-1]
        logs["captured_bytes"] += len(kept)
        if len(kept) < len(encoded):
            logs["truncated"] = True
        return result

    def _append_script_log(self, logs, attempt, sequence, stream, text):
        kept = self._append_log_text(logs, text)
        if kept:
            attempt["console"].append(
                {"sequence": sequence, "stream": stream, "content": kept}
            )

    def _execute_llm(
        self, workflow, node, node_execution_id, context, controller, on_running=None
    ):
        document = self._base_node(workflow, node, node_execution_id)
        document.update(
            {
                "model": None,
                "request": None,
                "response": None,
                "response_received": False,
                "usage": None,
                "usage_errors": [],
                "attempts": [],
            }
        )
        missing_fields = []
        if not node.model.provider_id.strip():
            missing_fields.append("model.provider_id")
        if not node.model.model_name.strip():
            missing_fields.append("model.model_name")
        for index, message in enumerate(node.context.messages):
            if message.role != "SYSTEM" and not message.content.strip():
                missing_fields.append(f"context.messages[{index}].content")
        last_message = node.context.messages[-1]
        if last_message.role != "USER":
            missing_fields.append(f"context.messages[{len(node.context.messages) - 1}].role")
        generation_parameters = node.generation.parameters
        parameters_text = node.generation.parameters_text.strip()
        if parameters_text:
            try:
                parsed_parameters = json.loads(parameters_text)
                if not isinstance(parsed_parameters, dict):
                    raise ValueError("高级参数必须是 JSON 对象")
                generation_parameters = parsed_parameters
            except (json.JSONDecodeError, ValueError):
                missing_fields.append("generation.parameters_text")
        if missing_fields:
            error = self._missing_configuration_error(
                "LLM_CONFIGURATION_INCOMPLETE",
                node.name,
                "未完成模型配置",
                missing_fields,
                "打开节点设置，选择供应商和模型，补全上下文，并确保高级参数是 JSON 对象",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        provider = self.model_repository.get(node.model.provider_id)
        if provider is None or node.model.model_name not in provider.models:
            error = self._missing_configuration_error(
                "LLM_MODEL_NOT_FOUND",
                node.name,
                f"引用的模型“{node.model.provider_id}/{node.model.model_name}”不存在或已被删除",
                [],
                "打开节点设置，重新选择模型管理中的可用模型",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        started = self._begin_business_node(document, node, controller, on_running)
        if started is None:
            return document, {}
        try:
            resolved_messages = []
            inputs: dict[str, Any] = {}
            for message in node.context.messages:
                content, used = resolve_template(
                    message.content, context, force_text=True
                )
                inputs.update(used)
                if message.role == "SYSTEM" and not content.strip():
                    continue
                if message.role != "SYSTEM" and not content.strip():
                    raise WorkflowValueError(
                        f"LLM {message.role} 消息解析后为空"
                    )
                resolved_messages.append(
                    {"role": message.role.lower(), "content": content}
                )
            document["inputs"] = inputs
            document["model"] = node.model.model_dump(mode="json")
            defaults = provider.model_configs.get(node.model.model_name)
            default_body = defaults.default_body if defaults else {}
            if provider.protocol == "ANTHROPIC":
                system_prompt = ""
                anthropic_messages = []
                for message in resolved_messages:
                    if message["role"] == "system":
                        system_prompt = message["content"]
                    else:
                        anthropic_messages.append(message)
                request_body = build_anthropic_request(
                    model_name=node.model.model_name,
                    system_prompt=system_prompt,
                    messages=anthropic_messages,
                    model_defaults=default_body,
                    model_parameters=generation_parameters,
                )
                url = anthropic_messages_url(provider.base_url)
                headers = anthropic_headers(provider.api_key)
            else:
                request_body = build_chat_completion_request(
                    model_name=node.model.model_name,
                    messages=resolved_messages,
                    model_defaults=default_body,
                    model_parameters=generation_parameters,
                )
                url = chat_completions_url(provider.base_url)
                headers = {
                    "accept": "application/json",
                    "authorization": f"Bearer {provider.api_key}",
                    "content-type": "application/json",
                }
            request_body["stream"] = False
        except (WorkflowValueError, ValueError) as exc:
            code = (
                "LLM_MESSAGE_EMPTY"
                if str(exc).startswith("LLM ") and str(exc).endswith("消息解析后为空")
                else "LLM_EXECUTION_ERROR"
            )
            error = _error(code, str(exc))
            self._finish_node(document, "FAILED", started, error=error)
            return document, {}

        final_status = "FAILED"
        final_error = None
        outputs: dict[str, Any] = {}
        usage_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for attempt_number in range(1, node.execution.max_attempts + 2):
            if controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
                break
            attempt_started = time.monotonic()
            attempt = {
                "attempt": attempt_number,
                "status": "RUNNING",
                "started_at": local_execution_time(),
                "finished_at": None,
                "duration_ms": None,
                "request": strict_json_clone(request_body),
                "response": None,
                "response_received": False,
                "error": None,
                "truncated_fields": [],
            }
            document["attempts"].append(attempt)
            document["attempt_count"] = attempt_number
            document["request"] = strict_json_clone(request_body)
            self.store.write_node(document)
            controller.add_worker(node_execution_id)
            try:
                result = stream_tool_worker(
                    {
                        "mode": "RAW_HTTP",
                        "inputs": {},
                        "config": {
                            "timeout_seconds": seconds_to_milliseconds(
                                node.execution.timeout_seconds
                            )
                            / 1000
                        },
                        "request": {
                            "method": "POST",
                            "url": url,
                            "headers": headers,
                            "body_mode": "JSON",
                            "body": request_body,
                            "execution_body_type": "raw",
                            "execution_body": request_body,
                        },
                        "network": {
                            "proxy": {
                                "mode": provider.proxy_mode,
                                "url": provider.proxy_url,
                                "username": provider.proxy_username,
                                "password": provider.proxy_password,
                            },
                            "verify_ssl": provider.verify_ssl,
                        },
                    },
                    lambda _text: None,
                    node_execution_id,
                    timeout_seconds=(
                        seconds_to_milliseconds(node.execution.timeout_seconds) / 1000 + 2
                    ),
                )
            finally:
                controller.remove_worker(node_execution_id)
            attempt["finished_at"] = local_execution_time()
            attempt["duration_ms"] = max(0, round((time.monotonic() - attempt_started) * 1000))
            if result.get("interrupted") or controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
            elif result.get("timed_out"):
                final_status = "TIMEOUT"
                final_error = _error("LLM_TIMEOUT", "LLM 请求超时")
            elif not result.get("ok"):
                final_status = "FAILED"
                final_error = _error("LLM_REQUEST_FAILED", result.get("error") or "模型请求失败")
            else:
                response_fact = result["response"]["response"]
                raw_response = response_fact["body"]
                attempt["response"] = strict_json_clone(raw_response)
                attempt["response_received"] = True
                document["response"] = strict_json_clone(raw_response)
                document["response_received"] = True
                self._accumulate_usage(raw_response, usage_total)
                if response_fact["status_code"] < 200 or response_fact["status_code"] >= 300:
                    final_status = "FAILED"
                    final_error = _error(
                        "LLM_RESPONSE_ERROR",
                        f"供应商返回 HTTP {response_fact['status_code']}",
                        {"status_code": response_fact["status_code"]},
                    )
                else:
                    try:
                        outputs = collect_outputs(node.outputs, {"response": raw_response})
                    except WorkflowOutputSourceError as exc:
                        final_status = "FAILED"
                        final_error = _error(
                            "LLM_OUTPUT_SOURCE_EVALUATION_ERROR", str(exc)
                        )
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    except WorkflowOutputTypeError as exc:
                        final_status = "FAILED"
                        final_error = _error("LLM_OUTPUT_TYPE_MISMATCH", str(exc))
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    final_status = "SUCCESS"
                    final_error = None
            attempt.update({"status": final_status, "error": final_error})
            if final_status == "SUCCESS" or final_status == "INTERRUPTED":
                break
            if attempt_number <= node.execution.max_attempts:
                if self._wait_interruptibly(
                    controller,
                    seconds_to_milliseconds(node.execution.retry_interval_seconds),
                ):
                    break
        document["usage"] = usage_total if any(usage_total.values()) else None
        document["outputs"] = strict_json_clone(outputs) if final_status == "SUCCESS" else {}
        self._finish_node(document, final_status, started, error=final_error)
        return document, outputs if final_status == "SUCCESS" else {}

    @staticmethod
    def _accumulate_usage(response: Any, total: dict[str, int]) -> None:
        if not isinstance(response, dict) or not isinstance(response.get("usage"), dict):
            return
        usage = response["usage"]
        input_value = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        output_value = usage.get("completion_tokens", usage.get("output_tokens", 0))
        if isinstance(input_value, int) and input_value >= 0:
            total["input_tokens"] += input_value
        if isinstance(output_value, int) and output_value >= 0:
            total["output_tokens"] += output_value
        total_value = usage.get("total_tokens")
        if isinstance(total_value, int) and total_value >= 0:
            total["total_tokens"] += total_value
        else:
            total["total_tokens"] = total["input_tokens"] + total["output_tokens"]

    def _execute_http(
        self, workflow, node, node_execution_id, context, controller, on_running=None
    ):
        document = self._base_node(workflow, node, node_execution_id)
        document.update(
            {"network": node.network.model_dump(mode="json"), "request": None, "redirects": [], "response": None, "attempts": []}
        )
        missing_fields = []
        if not node.request.url.strip():
            missing_fields.append("request.url")
        if node.network.proxy.mode == "CUSTOM" and not node.network.proxy.url:
            missing_fields.append("network.proxy.url")
        if missing_fields:
            error = self._missing_configuration_error(
                "HTTP_CONFIGURATION_INCOMPLETE",
                node.name,
                "未完成请求配置",
                missing_fields,
                "打开节点设置，填写请求 URL；CUSTOM 模式还必须填写 Proxy URL",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        started = self._begin_business_node(document, node, controller, on_running)
        if started is None:
            return document, {}
        try:
            resolved_url, url_inputs = resolve_template(node.request.url, context)
            headers = []
            inputs = dict(url_inputs)
            for header in node.request.headers:
                value, used = resolve_template(header.value, context, force_text=True)
                headers.append({"key": header.key, "value": value})
                inputs.update(used)
            params = []
            for parameter in node.request.params:
                value, used = resolve_template(parameter.value, context)
                if isinstance(value, (dict, list)):
                    raise WorkflowValueError("HTTP Query 参数必须是 JSON 标量")
                params.append([parameter.key, value])
                inputs.update(used)
            structural_body = node.request.body.model_dump(mode="json")["content"]
            body, body_inputs = resolve_template(structural_body, context)
            inputs.update(body_inputs)
            document["inputs"] = inputs
        except WorkflowValueError as exc:
            error = _error("HTTP_CONTEXT_RESOLUTION_ERROR", str(exc))
            self._finish_node(document, "FAILED", started, error=error)
            return document, {}

        body_mode = {
            "none": "NONE",
            "raw": "JSON",
            "form_data": "FORM_DATA",
            "form_urlencoded": "FORM_URLENCODED",
        }[node.request.body.type]
        final_status = "FAILED"
        final_error = None
        outputs: dict[str, Any] = {}
        for attempt_number in range(1, node.execution.max_attempts + 2):
            if controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
                break
            attempt_started = time.monotonic()
            attempt = {
                "attempt": attempt_number,
                "status": "RUNNING",
                "started_at": local_execution_time(),
                "finished_at": None,
                "duration_ms": None,
                "request": None,
                "redirects": [],
                "response": None,
                "error": None,
            }
            document["attempts"].append(attempt)
            document["attempt_count"] = attempt_number
            self.store.write_node(document)
            controller.add_worker(node_execution_id)
            try:
                result = stream_tool_worker(
                    {
                        "mode": "RAW_HTTP",
                        "inputs": {},
                        "config": {
                            "timeout_seconds": seconds_to_milliseconds(
                                node.execution.timeout_seconds
                            )
                            / 1000
                        },
                        "request": {
                            "method": node.request.method,
                            "url": resolved_url,
                            "headers": headers,
                            "params": params,
                            "body_mode": body_mode,
                            "body": body,
                            "follow_redirects": node.request.follow_redirects,
                            "response_mode": node.response.mode,
                            "execution_body_type": node.request.body.type,
                            "execution_body": body,
                        },
                        "network": node.network.model_dump(mode="json"),
                    },
                    lambda _text: None,
                    node_execution_id,
                    timeout_seconds=(
                        seconds_to_milliseconds(node.execution.timeout_seconds) / 1000 + 2
                    ),
                )
            finally:
                controller.remove_worker(node_execution_id)
            attempt["finished_at"] = local_execution_time()
            attempt["duration_ms"] = max(0, round((time.monotonic() - attempt_started) * 1000))
            if result.get("interrupted") or controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
            elif result.get("timed_out"):
                final_status = "TIMEOUT"
                final_error = _error("HTTP_TIMEOUT", "HTTP 请求超时")
            elif not result.get("ok"):
                final_status = "FAILED"
                worker_error_code = result.get("error_code")
                if worker_error_code == "HTTP_RESPONSE_PARSE_ERROR":
                    final_error = _error(
                        worker_error_code,
                        result.get("error") or "HTTP 响应 Body 解析失败",
                    )
                else:
                    final_error = _error(
                        "HTTP_CONNECTION_ERROR",
                        result.get("error") or "HTTP 请求失败",
                        {"stage": "TCP", "raw_error": result.get("error")},
                    )
            else:
                facts = result["response"]
                attempt.update(
                    {
                        "request": facts["request"],
                        "redirects": facts["redirects"],
                        "response": facts["response"],
                    }
                )
                document.update(
                    {
                        "request": facts["request"],
                        "redirects": facts["redirects"],
                        "response": facts["response"],
                    }
                )
                status_code = facts["response"]["status_code"]
                if not self._status_success(status_code, node.response.success_statuses):
                    final_status = "FAILED"
                    final_error = _error(
                        "HTTP_STATUS_ERROR",
                        f"HTTP 返回状态码 {status_code}",
                        {"status_code": status_code},
                    )
                else:
                    try:
                        outputs = collect_outputs(
                            node.outputs,
                            {"request": facts["request"], "response": facts["response"]},
                        )
                    except WorkflowOutputSourceError as exc:
                        final_status = "FAILED"
                        final_error = _error(
                            "HTTP_OUTPUT_SOURCE_EVALUATION_ERROR", str(exc)
                        )
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    except WorkflowOutputTypeError as exc:
                        final_status = "FAILED"
                        final_error = _error("HTTP_OUTPUT_TYPE_MISMATCH", str(exc))
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    final_status = "SUCCESS"
                    final_error = None
            attempt.update({"status": final_status, "error": final_error})
            if final_status in {"SUCCESS", "INTERRUPTED"}:
                break
            failed_status = (
                attempt["response"]["status_code"]
                if attempt.get("response") is not None
                else None
            )
            retryable_failure = (
                final_error.get("code") != "HTTP_RESPONSE_PARSE_ERROR"
                and (failed_status is None or failed_status in node.execution.retry_statuses)
            )
            can_retry = (
                node.request.method not in {"POST", "PATCH"}
                or node.execution.retry_non_idempotent
            ) and retryable_failure
            if attempt_number <= node.execution.max_attempts and can_retry:
                if self._wait_interruptibly(
                    controller,
                    seconds_to_milliseconds(node.execution.retry_interval_seconds),
                ):
                    break
            else:
                break
        document["outputs"] = strict_json_clone(outputs) if final_status == "SUCCESS" else {}
        self._finish_node(document, final_status, started, error=final_error)
        return document, outputs if final_status == "SUCCESS" else {}

    @staticmethod
    def _status_success(status: int, declarations: list[int | str]) -> bool:
        for declaration in declarations:
            if isinstance(declaration, int) and status == declaration:
                return True
            if isinstance(declaration, str):
                start, end = (int(part) for part in declaration.split("-"))
                if start <= status <= end:
                    return True
        return False

    @staticmethod
    def _workflow_node(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
        return next(item for item in workflow["nodes"] if item["node_id"] == node_id)


_NODE_TEST_TERMINAL_STATUSES = {"SUCCESS", "FAILED", "TIMEOUT", "INTERRUPTED"}
_NODE_TEST_RETENTION_SECONDS = 300


def _node_test_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    """移除只属于持久化 Node Execution 的身份和结构快照字段。"""

    snapshot = deepcopy(document)
    for field_name in (
        "workflow_execution_id",
        "workflow_id",
        "node_execution_id",
        "structural_snapshot",
        "transitions",
    ):
        snapshot.pop(field_name, None)
    return strict_json_clone(snapshot)


@dataclass
class _NodeTestSession:
    """一次活动单节点临时测试的进程内状态和有界事件队列。"""

    test_id: str
    workflow_id: str
    node_id: str
    node_type: str
    controller: _ExecutionController
    snapshot: dict[str, Any]
    events: queue.Queue[dict[str, Any]] = field(default_factory=lambda: queue.Queue(maxsize=16))
    connected: bool = False
    terminal: bool = False
    finished_at: float | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def publish(self, event: dict[str, Any]) -> None:
        """保留最近实时快照，并保证终态事件一定可被消费。"""

        while True:
            try:
                self.events.put_nowait(event)
                return
            except queue.Full:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    return


class _TransientNodeStore:
    """只把执行器写入映射为内存快照，绝不访问文件系统。"""

    def __init__(self, on_snapshot):
        self.on_snapshot = on_snapshot

    def recover_incomplete(self) -> int:
        return 0

    def write_workflow(self, _document: dict[str, Any]) -> None:
        return None

    def write_node(self, document: dict[str, Any]) -> None:
        self.on_snapshot(_node_test_snapshot(document))


class NodeTestManager:
    """运行不落库、不写 JSON 的单节点草稿测试，并通过 SSE 交付最终前端快照。"""

    def __init__(
        self,
        structural_repository: WorkflowStructuralRepository,
        model_repository: ModelProviderRepository,
    ):
        self.structural_repository = structural_repository
        self.model_repository = model_repository
        self._sessions: dict[str, _NodeTestSession] = {}
        self._active_by_node: dict[tuple[str, str], str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def start(
        self,
        workflow_id: str,
        node: NodeStructuralModel,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """幂等启动同一 Workflow/Node 的临时测试，返回初始前端快照。"""

        if node.type == "END":
            raise WorkflowExecutionError("END 不提供单节点临时测试")
        cloned_context = strict_json_clone(context)
        self._cleanup()
        key = (workflow_id, node.id)
        with self._lock:
            existing_id = self._active_by_node.get(key)
            if existing_id:
                existing = self._sessions.get(existing_id)
                if existing and not existing.terminal:
                    return self._envelope(existing), False
            test_id = str(uuid4())
            snapshot = {
                "node_id": node.id,
                "type": node.type,
                "status": "PENDING",
                "started_at": None,
                "finished_at": None,
                "duration_ms": None,
                "attempt_count": 0,
                "inputs": {},
                "outputs": {},
                "error": None,
            }
            session = _NodeTestSession(
                test_id=test_id,
                workflow_id=workflow_id,
                node_id=node.id,
                node_type=node.type,
                controller=_ExecutionController(),
                snapshot=snapshot,
            )
            self._sessions[test_id] = session
            self._active_by_node[key] = test_id
            session.publish({"type": "snapshot", "snapshot": deepcopy(snapshot)})
            thread = threading.Thread(
                target=self._run,
                args=(session, node, cloned_context),
                daemon=True,
                name=f"node-test-{test_id}",
            )
            self._threads[test_id] = thread
        thread.start()
        return self._envelope(session), True

    def cancel(self, workflow_id: str, test_id: str) -> bool:
        """幂等中断属于指定 Workflow 的活动节点测试及其进程树。"""

        with self._lock:
            session = self._sessions.get(test_id)
        if session is None or session.workflow_id != workflow_id or session.terminal:
            return False
        session.controller.user_cancel.set()
        session.controller.interrupt_workers()
        return True

    def cancel_node(self, workflow_id: str, node_id: str, *, wait_seconds: float = 5) -> bool:
        """中断一个节点的活动测试，并等待 Worker 收敛供结构删除使用。"""

        with self._lock:
            test_id = self._active_by_node.get((workflow_id, node_id))
        if test_id is None:
            return False
        self.cancel(workflow_id, test_id)
        self._wait(test_id, wait_seconds)
        return True

    def cancel_workflow(self, workflow_id: str, *, wait_seconds: float = 5) -> int:
        """中断一个 Workflow 下全部活动节点测试并等待收敛。"""

        with self._lock:
            test_ids = [
                test_id
                for (active_workflow_id, _node_id), test_id in self._active_by_node.items()
                if active_workflow_id == workflow_id
            ]
        for test_id in test_ids:
            self.cancel(workflow_id, test_id)
        for test_id in test_ids:
            self._wait(test_id, wait_seconds)
        return len(test_ids)

    def iter_events(
        self,
        workflow_id: str,
        test_id: str,
        *,
        keepalive_seconds: float = 15,
    ) -> Iterator[dict[str, Any] | None]:
        """按顺序交付实时快照和唯一终态事件，交付后立即释放服务端会话。"""

        with self._lock:
            session = self._sessions.get(test_id)
        if session is None or session.workflow_id != workflow_id:
            raise WorkflowExecutionError(f"节点临时测试不存在: {test_id}")
        with session.lock:
            if session.connected:
                raise WorkflowExecutionError(f"节点临时测试事件已连接: {test_id}")
            session.connected = True
        terminal_seen = False
        try:
            while not terminal_seen:
                try:
                    event = session.events.get(timeout=keepalive_seconds)
                except queue.Empty:
                    yield None
                    continue
                terminal_seen = event.get("type") in {"complete", "interrupted"}
                yield event
        finally:
            with session.lock:
                session.connected = False
            if terminal_seen:
                with self._lock:
                    self._sessions.pop(test_id, None)
                    self._threads.pop(test_id, None)

    def _run(
        self,
        session: _NodeTestSession,
        node: NodeStructuralModel,
        context: dict[str, Any],
    ) -> None:
        transient_store = _TransientNodeStore(
            lambda snapshot: self._publish_snapshot(session, snapshot)
        )
        engine = WorkflowExecutionManager(
            self.structural_repository,
            self.model_repository,
            transient_store,  # type: ignore[arg-type]
        )
        workflow = {"id": str(uuid4()), "workflow_id": session.workflow_id}
        try:
            if node.type == "START":
                document, _outputs = engine._execute_start(
                    workflow, node, session.test_id, {}
                )
            elif node.type == "SCRIPT":
                document, _outputs = engine._execute_script(
                    workflow, node, session.test_id, context, session.controller
                )
            elif node.type == "LLM":
                document, _outputs = engine._execute_llm(
                    workflow, node, session.test_id, context, session.controller
                )
            elif node.type == "HTTP":
                document, _outputs = engine._execute_http(
                    workflow, node, session.test_id, context, session.controller
                )
            else:
                raise WorkflowExecutionError(f"不支持的 Node 类型: {node.type}")
            if session.controller.user_cancel.is_set():
                document["status"] = "INTERRUPTED"
                document["outputs"] = {}
                document["error"] = _error("USER_INTERRUPTED", "用户中断节点临时测试")
            transient_store.write_node(document)
        except Exception as exc:  # noqa: BLE001
            snapshot = deepcopy(session.snapshot)
            snapshot.update(
                {
                    "status": "FAILED",
                    "finished_at": local_execution_time(),
                    "duration_ms": snapshot.get("duration_ms") or 0,
                    "outputs": {},
                    "error": _error("NODE_TEST_FAILED", str(exc)),
                }
            )
            self._publish_snapshot(session, snapshot)
        finally:
            with session.lock:
                if session.snapshot.get("status") not in _NODE_TEST_TERMINAL_STATUSES:
                    session.snapshot.update(
                        {
                            "status": "FAILED",
                            "finished_at": local_execution_time(),
                            "duration_ms": session.snapshot.get("duration_ms") or 0,
                            "error": _error(
                                "NODE_TEST_FAILED", "节点临时测试未产生终态"
                            ),
                        }
                    )
                session.terminal = True
                session.finished_at = time.monotonic()
                final_snapshot = strict_json_clone(session.snapshot)
            with self._lock:
                self._active_by_node.pop((session.workflow_id, session.node_id), None)
                self._threads.pop(session.test_id, None)
            event_type = (
                "interrupted"
                if final_snapshot["status"] == "INTERRUPTED"
                else "complete"
            )
            session.publish({"type": event_type, "snapshot": final_snapshot})

    @staticmethod
    def _envelope(session: _NodeTestSession) -> dict[str, Any]:
        with session.lock:
            return {
                "test_id": session.test_id,
                "node_id": session.node_id,
                "status": session.snapshot["status"],
                "snapshot": strict_json_clone(session.snapshot),
            }

    @staticmethod
    def _publish_snapshot(session: _NodeTestSession, snapshot: dict[str, Any]) -> None:
        with session.lock:
            session.snapshot = strict_json_clone(snapshot)
            current = strict_json_clone(session.snapshot)
        session.publish({"type": "snapshot", "snapshot": current})

    def _wait(self, test_id: str, wait_seconds: float) -> None:
        with self._lock:
            thread = self._threads.get(test_id)
        if thread is not None:
            thread.join(timeout=max(0, wait_seconds))
        if thread is not None and thread.is_alive():
            raise WorkflowExecutionError(f"节点临时测试未能及时终止: {test_id}")

    def _cleanup(self) -> None:
        now = time.monotonic()
        with self._lock:
            expired = [
                test_id
                for test_id, session in self._sessions.items()
                if session.finished_at is not None
                and now - session.finished_at > _NODE_TEST_RETENTION_SECONDS
            ]
            for test_id in expired:
                self._sessions.pop(test_id, None)
                self._threads.pop(test_id, None)
