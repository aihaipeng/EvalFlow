"""Concurrent DAG executor for the new Workflow protocol."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from execution.workflow_contract import (
    HttpNode,
    LlmNode,
    NodeDefinition,
    NodeStatus,
    NodeType,
    ScriptNode,
    StartNode,
    WorkflowDefinition,
    value_matches_type,
)
from execution.workflows import (
    NodeRunRecord,
    RuntimeErrorRecord,
    WorkflowRepository,
    WorkflowRunRecord,
    WorkflowRunStatus,
    workflow_now,
)


class NodeExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class NodeExecutionResult:
    outputs: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] | None = None
    network: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    response: Any = None
    usage: dict[str, Any] | None = None
    usage_errors: list[dict[str, Any]] = field(default_factory=list)


NodeAdapter = Callable[[NodeDefinition, dict[str, Any]], Awaitable[NodeExecutionResult]]


class WorkflowExecutor:
    def __init__(self, repository: WorkflowRepository, adapter: NodeAdapter):
        self.repository = repository
        self.adapter = adapter
        self._context_lock = asyncio.Lock()

    async def run(self, workflow: WorkflowDefinition, *, run_id: str | None = None) -> WorkflowRunRecord:
        values = {"workflow_id": workflow.workflow_id}
        if run_id is not None:
            values["run_id"] = run_id
        workflow_run = self.repository.create_workflow_run(WorkflowRunRecord.model_validate(values))
        started = workflow_now()
        overall_started = time.monotonic()
        workflow_run = WorkflowRunRecord.model_validate({**workflow_run.model_dump(mode="json"), "status": "RUNNING", "started_at": started})
        self.repository.update_workflow_run(workflow_run)
        context: dict[str, Any] = {}
        nodes = {node.id: node for node in workflow.nodes if node.type != NodeType.END}
        predecessors = {node_id: set() for node_id in nodes}
        for edge in workflow.edges:
            if edge.target in predecessors and edge.source in nodes:
                predecessors[edge.target].add(edge.source)
        statuses: dict[str, NodeStatus] = {}
        tasks: dict[asyncio.Task[tuple[str, NodeStatus]], str] = {}
        started_nodes: set[str] = set()
        failed_error: RuntimeErrorRecord | None = None
        try:
            while len(statuses) < len(nodes):
                ready = [
                    node_id for node_id, deps in predecessors.items()
                    if node_id not in started_nodes and all(statuses.get(dep) == NodeStatus.SUCCESS for dep in deps)
                ]
                for node_id in ready:
                    started_nodes.add(node_id)
                    task = asyncio.create_task(self._run_node(workflow_run.run_id, nodes[node_id], context))
                    tasks[task] = node_id
                if not tasks:
                    failed_error = RuntimeErrorRecord(code="WORKFLOW_GRAPH_INVALID", message="No runnable Workflow node remains")
                    break
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    node_id = tasks.pop(task)
                    try:
                        status = task.result()[1]
                    except Exception as exc:
                        status = NodeStatus.FAILED
                        failed_error = RuntimeErrorRecord(
                            code="WORKFLOW_CONFIG_INVALID",
                            message=f"Node task terminated unexpectedly: {exc}",
                        )
                    statuses[node_id] = status
                    if status != NodeStatus.SUCCESS:
                        if failed_error is None:
                            node_runs = self.repository.list_node_runs(workflow_run.run_id)
                            failed = next((run for run in node_runs if run.node_id == node_id), None)
                            failed_error = RuntimeErrorRecord(
                                code=failed.error.code if failed and failed.error else "WORKFLOW_CONFIG_INVALID",
                                message=failed.error.message if failed and failed.error else "Node failed without an error record",
                                node_run_id=failed.node_run_id if failed else None,
                            )
                        break
                if failed_error:
                    for task in tasks:
                        task.cancel(f"fail_fast:{failed_error.node_run_id or ''}")
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break
            elapsed = max(0, int((time.monotonic() - overall_started) * 1000))
            if failed_error:
                terminal = WorkflowRunRecord.model_validate({**workflow_run.model_dump(mode="json"), "status": "FAILED", "finished_at": workflow_now(), "duration_ms": elapsed, "error": failed_error.model_dump(mode="json")})
            else:
                terminal = WorkflowRunRecord.model_validate({**workflow_run.model_dump(mode="json"), "status": "SUCCESS", "finished_at": workflow_now(), "duration_ms": elapsed})
            return self.repository.update_workflow_run(terminal)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel("user")
            await asyncio.gather(*tasks, return_exceptions=True)
            terminal = WorkflowRunRecord.model_validate({**workflow_run.model_dump(mode="json"), "status": "CANCELLED", "finished_at": workflow_now(), "duration_ms": max(0, int((time.monotonic() - overall_started) * 1000)), "error": {"code": "WORKFLOW_CANCELLED", "message": "Workflow cancelled"}})
            return self.repository.update_workflow_run(terminal)
        except Exception as exc:
            terminal = WorkflowRunRecord.model_validate({
                **workflow_run.model_dump(mode="json"),
                "status": "FAILED",
                "finished_at": workflow_now(),
                "duration_ms": max(0, int((time.monotonic() - overall_started) * 1000)),
                "error": {"code": "WORKFLOW_CONFIG_INVALID", "message": f"Workflow execution failed: {exc}"},
            })
            return self.repository.update_workflow_run(terminal)

    async def _run_node(self, run_id: str, node: NodeDefinition, context: dict[str, Any]) -> tuple[str, NodeStatus]:
        pending = self.repository.create_node_run(NodeRunRecord(run_id=run_id, node_id=node.id, type=node.type))
        started_at = workflow_now()
        running = NodeRunRecord.model_validate({**pending.model_dump(mode="json"), "status": "RUNNING", "started_at": started_at})
        self.repository.update_node_run(running)
        started = time.monotonic()
        attempt_count = 0
        try:
            result, attempt_count = await self._execute_with_retries(node, context)
            self._validate_outputs(node, result.outputs)
            async with self._context_lock:
                duplicates = set(result.outputs) & set(context)
                if duplicates:
                    raise NodeExecutionError("CONTEXT_KEY_EXISTS", "Context key already exists")
                completed = NodeRunRecord.model_validate({**running.model_dump(mode="json"), "status": "SUCCESS", "finished_at": workflow_now(), "duration_ms": int((time.monotonic() - started) * 1000), "attempt_count": attempt_count, **result.__dict__})
                self.repository.update_node_run(completed)
                context.update(result.outputs)
            return node.id, NodeStatus.SUCCESS
        except asyncio.CancelledError as cancellation:
            # asyncio.CancelledError carries the marker supplied to Task.cancel().
            # User cancellation has no marker; fail-fast uses fail_fast:<node_run_id>.
            cancelled_error = "NODE_CANCELLED_BY_USER"
            details = None
            marker = cancellation.args[0] if cancellation.args else None
            if isinstance(marker, str) and marker.startswith("fail_fast:"):
                cancelled_error = "NODE_CANCELLED_BY_FAIL_FAST"
                trigger = marker.split(":", 1)[1]
                details = {"trigger_node_run_id": trigger} if trigger else None
            cancelled = NodeRunRecord.model_validate({**running.model_dump(mode="json"), "status": "CANCELLED", "finished_at": workflow_now(), "duration_ms": int((time.monotonic() - started) * 1000), "error": {"code": cancelled_error, "message": "Node cancelled by user" if cancelled_error == "NODE_CANCELLED_BY_USER" else "Node cancelled by fail-fast", "details": details}})
            self.repository.update_node_run(cancelled)
            return node.id, NodeStatus.CANCELLED
        except NodeExecutionError as exc:
            status = "TIMEOUT" if exc.code in {"SCRIPT_TIMEOUT", "LLM_TIMEOUT", "HTTP_TIMEOUT"} else "FAILED"
            failed = NodeRunRecord.model_validate({**running.model_dump(mode="json"), "status": status, "finished_at": workflow_now(), "duration_ms": int((time.monotonic() - started) * 1000), "attempt_count": attempt_count, "error": {"code": exc.code, "message": str(exc), "details": exc.details}})
            self.repository.update_node_run(failed)
            return node.id, NodeStatus.FAILED
        except Exception as exc:
            code = {NodeType.HTTP: "HTTP_EXECUTION_ERROR", NodeType.LLM: "LLM_EXECUTION_ERROR"}.get(node.type, "SCRIPT_EXECUTION_ERROR")
            failed = NodeRunRecord.model_validate({**running.model_dump(mode="json"), "status": "FAILED", "finished_at": workflow_now(), "duration_ms": int((time.monotonic() - started) * 1000), "attempt_count": attempt_count, "error": {"code": code, "message": str(exc)}})
            self.repository.update_node_run(failed)
            return node.id, NodeStatus.FAILED

    async def _execute(self, node: NodeDefinition, context: dict[str, Any]) -> NodeExecutionResult:
        if isinstance(node, StartNode):
            outputs = {item.name: item.data for item in node.inputs}
            return NodeExecutionResult(inputs=outputs, outputs=outputs)
        return await self.adapter(node, dict(context))

    async def _execute_with_retries(self, node: NodeDefinition, context: dict[str, Any]) -> tuple[NodeExecutionResult, int]:
        if isinstance(node, StartNode):
            return await self._execute(node, context), 1
        execution = node.execution
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await asyncio.wait_for(self._execute(node, context), timeout=execution.timeout_ms / 1000)
                return result, attempt
            except asyncio.TimeoutError as exc:
                code = {NodeType.SCRIPT: "SCRIPT_TIMEOUT", NodeType.LLM: "LLM_TIMEOUT", NodeType.HTTP: "HTTP_TIMEOUT"}[node.type]
                error = NodeExecutionError(code, f"Node attempt timed out after {execution.timeout_ms} ms")
                if attempt > execution.max_attempts or not self._retryable(node, error):
                    raise error from exc
            except NodeExecutionError as exc:
                if attempt > execution.max_attempts or not self._retryable(node, exc):
                    raise
            if execution.delay_ms:
                await asyncio.sleep(execution.delay_ms / 1000)

    @staticmethod
    def _retryable(node: NodeDefinition, error: NodeExecutionError) -> bool:
        if isinstance(node, ScriptNode):
            return True
        if isinstance(node, LlmNode):
            return error.code in {"LLM_TIMEOUT", "LLM_REQUEST_ERROR", "LLM_RESPONSE_ERROR", "LLM_STREAM_INCOMPLETE", "LLM_OUTPUT_TRUNCATED", "LLM_CONTENT_FILTERED", "LLM_UNSUPPORTED_FINISH_REASON"}
        if isinstance(node, HttpNode):
            if node.request.method not in {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}:
                return False
            if error.code in {"HTTP_CONNECTION_ERROR", "HTTP_TIMEOUT"}:
                return True
            status = (error.details or {}).get("response", {}).get("status_code")
            return error.code == "HTTP_STATUS_ERROR" and status in {408, 429, 500, 502, 503, 504}
        return False

    @staticmethod
    def _validate_outputs(node: NodeDefinition, outputs: dict[str, Any]) -> None:
        if isinstance(node, StartNode):
            return
        declarations = node.outputs if isinstance(node, (ScriptNode, LlmNode, HttpNode)) else []
        expected = {item.name: item.type for item in declarations}
        if set(outputs) != set(expected):
            raise NodeExecutionError("SCRIPT_OUTPUT_MISSING", "Node outputs do not match declarations")
        for name, declared_type in expected.items():
            if not value_matches_type(outputs[name], declared_type):
                raise NodeExecutionError("SCRIPT_OUTPUT_TYPE_MISMATCH", "Node output type does not match declaration")
