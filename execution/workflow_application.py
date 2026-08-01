"""Application-level transactions spanning Workflow resources."""

from __future__ import annotations

from execution.node_structural_models import NodeStructuralModel
from execution.workflow_execution import WorkflowExecutionManager
from execution.workflow_execution_store import WorkflowExecutionError
from execution.workflow_node_tests import NodeTestManager
from execution.workflow_structural_models import (
    WorkflowStructuralModel,
    WorkflowStructuralRecord,
    WorkflowStructuralRepository,
    validate_workflow_graph,
)


class WorkflowApplicationNotFoundError(RuntimeError):
    pass


class WorkflowApplicationConflictError(RuntimeError):
    pass


class WorkflowApplicationService:
    def __init__(
        self,
        repository: WorkflowStructuralRepository,
        manager: WorkflowExecutionManager,
        node_test_manager: NodeTestManager,
    ) -> None:
        self.repository = repository
        self.manager = manager
        self.node_test_manager = node_test_manager

    def update_workflow(
        self,
        workflow: WorkflowStructuralModel,
        nodes: list[NodeStructuralModel],
    ) -> WorkflowStructuralRecord:
        current = self.repository.get(workflow.id)
        if current is None:
            raise WorkflowApplicationNotFoundError(f"Workflow 不存在: {workflow.id}")
        validate_workflow_graph(workflow, nodes)
        next_node_ids = {node.id for node in nodes}
        removed_node_ids = {
            node.id for node in current.node_models if node.id not in next_node_ids
        }
        try:
            for node_id in removed_node_ids:
                self.node_test_manager.cancel_node(workflow.id, node_id)
        except WorkflowExecutionError as exc:
            raise WorkflowApplicationConflictError(str(exc)) from exc
        return self.repository.update(workflow, nodes)

    def delete_workflow(self, workflow_id: str) -> WorkflowStructuralRecord:
        current = self.repository.get(workflow_id)
        if current is None:
            raise WorkflowApplicationNotFoundError(f"Workflow 不存在: {workflow_id}")
        try:
            self.node_test_manager.cancel_workflow(workflow_id)
        except WorkflowExecutionError as exc:
            raise WorkflowApplicationConflictError(str(exc)) from exc
        if self.manager.has_active_workflow(workflow_id):
            raise WorkflowApplicationConflictError(
                "Workflow 存在活动 Execution，请先全局中断并等待终态"
            )

        try:
            staged = self.manager.store.stage_workflow_root_deletion(workflow_id)
        except (OSError, WorkflowExecutionError):
            staged = None
        try:
            deleted = self.repository.delete(workflow_id)
        except Exception:
            try:
                self.manager.store.restore_workflow_root_deletion(workflow_id, staged)
            except (OSError, WorkflowExecutionError) as exc:
                raise WorkflowApplicationConflictError(
                    "Workflow 删除失败，且 Execution 目录恢复失败，请重启服务后重试"
                ) from exc
            raise
        if not deleted:
            try:
                self.manager.store.restore_workflow_root_deletion(workflow_id, staged)
            except (OSError, WorkflowExecutionError) as exc:
                raise WorkflowApplicationConflictError(
                    "Workflow 删除失败，且 Execution 目录恢复失败，请重启服务后重试"
                ) from exc
            raise WorkflowApplicationNotFoundError(f"Workflow 不存在: {workflow_id}")
        try:
            if staged is None:
                self.manager.store.delete_workflow_root(workflow_id)
            else:
                self.manager.store.finalize_workflow_root_deletion(staged)
                self.manager.store.delete_archived_workflow(workflow_id)
        except (OSError, WorkflowExecutionError):
            pass
        return current
