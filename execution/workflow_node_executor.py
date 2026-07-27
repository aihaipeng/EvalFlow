"""Node-type dispatch and Context commit for Workflow executions."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from execution.model_providers import ModelProviderRepository
from execution.node_structural_models import NodeStructuralModel
from execution.workflow_execution_store import (
    WorkflowExecutionError,
    execution_error as _error,
    local_execution_time,
    utc_execution_time,
)
from execution.workflow_http_runner import HttpNodeRunner
from execution.workflow_llm_runner import LlmNodeRunner
from execution.workflow_node_runner_base import (
    ExecutionController,
    NodeExecutionStore,
    NodeRunnerBase,
)
from execution.workflow_script_runner import ScriptNodeRunner
from execution.workflow_values import WorkflowValueError, strict_json_clone


class WorkflowNodeExecutor:
    """Dispatch one structural Node while keeping Context commits atomic."""

    def __init__(
        self,
        model_repository: ModelProviderRepository,
        store: NodeExecutionStore,
        stream_worker: Any,
    ):
        self.lifecycle = NodeRunnerBase(model_repository, store, stream_worker)
        self.store = store
        self.runners = {
            "SCRIPT": ScriptNodeRunner(model_repository, store, stream_worker),
            "LLM": LlmNodeRunner(model_repository, store, stream_worker),
            "HTTP": HttpNodeRunner(model_repository, store, stream_worker),
        }

    def execute_transient(
        self,
        workflow: dict[str, Any],
        node: NodeStructuralModel,
        node_execution_id: str,
        context: dict[str, Any],
        controller: ExecutionController,
    ) -> dict[str, Any]:
        if node.type == "START":
            document, _outputs = self.lifecycle.execute_start(
                workflow, node, node_execution_id, {}
            )
        elif node.type in self.runners:
            document, _outputs = self.runners[node.type].run(
                workflow, node, node_execution_id, context, controller
            )
        else:
            raise WorkflowExecutionError(f"不支持的 Node 类型: {node.type}")
        return document

    def execute(
        self,
        workflow: dict[str, Any],
        node: NodeStructuralModel,
        context: dict[str, Any],
        controller: ExecutionController,
        commit,
    ) -> tuple[str, str]:
        node_execution_id = str(uuid4())
        entry = self._workflow_node(workflow, node.id)
        initial_state = "PENDING" if node.type in self.runners else "RUNNING"
        entry.update(
            {"node_execution_id": node_execution_id, "state": initial_state, "reason": None}
        )
        self.store.write_workflow(workflow)

        def mark_running() -> None:
            entry.update({"state": "RUNNING", "reason": None})
            self.store.write_workflow(workflow)

        if node.type == "START":
            document, outputs = self.lifecycle.execute_start(
                workflow, node, node_execution_id, context
            )
        elif node.type == "END":
            document, outputs = self.lifecycle.execute_end(
                workflow, node, node_execution_id, context
            )
        elif node.type in self.runners:
            document, outputs = self.runners[node.type].run(
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
                if node.type == "END":
                    workflow["result"] = strict_json_clone(outputs)
                else:
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

    @staticmethod
    def _workflow_node(workflow: dict[str, Any], node_id: str) -> dict[str, Any]:
        return next(item for item in workflow["nodes"] if item["node_id"] == node_id)
