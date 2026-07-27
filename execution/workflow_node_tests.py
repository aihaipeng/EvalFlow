"""In-memory node-test sessions and SSE event delivery."""

from __future__ import annotations

import queue
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterator
from uuid import uuid4

from execution.model_providers import ModelProviderRepository
from execution.node_structural_models import NodeStructuralModel
from execution.workflow_execution_control import ExecutionController
from execution.workflow_execution_store import (
    WorkflowExecutionError,
    execution_error as _error,
    local_execution_time,
)
from execution.workflow_node_executor import WorkflowNodeExecutor
from execution.workflow_values import strict_json_clone
from execution.tool_runtime import stream_tool_worker


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
    controller: ExecutionController
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
        model_repository: ModelProviderRepository,
    ):
        self.model_repository = model_repository
        self.stream_worker = stream_tool_worker
        self._sessions: dict[str, _NodeTestSession] = {}
        self._active_by_node: dict[tuple[str, str], str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._closed = False

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
            if self._closed:
                raise WorkflowExecutionError("Node Test Manager 已关闭")
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
                controller=ExecutionController(),
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

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        """拒绝新测试，中断全部活动测试并等待线程收敛。"""

        deadline = time.monotonic() + max(0, wait_seconds)
        with self._lock:
            self._closed = True
            sessions = list(self._sessions.values())
            threads = list(self._threads.items())
        for session in sessions:
            if not session.terminal:
                session.controller.user_cancel.set()
                session.controller.interrupt_workers()
        for _test_id, thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        active = [test_id for test_id, thread in threads if thread.is_alive()]
        if active:
            raise WorkflowExecutionError(
                f"节点临时测试未能及时终止: {', '.join(active)}"
            )
        with self._lock:
            self._sessions.clear()
            self._active_by_node.clear()
            self._threads.clear()

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
        executor = WorkflowNodeExecutor(
            self.model_repository,
            transient_store,
            self.stream_worker,
        )
        workflow = {"id": str(uuid4()), "workflow_id": session.workflow_id}
        try:
            document = executor.execute_transient(
                workflow,
                node,
                session.test_id,
                context,
                session.controller,
            )
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
