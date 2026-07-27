"""Application-scoped Workflow resources owned by the FastAPI lifespan."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from execution import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_EXECUTION_ROOT,
    ModelProviderRepository,
    NodeTestManager,
    WorkflowExecutionError,
    WorkflowExecutionManager,
    WorkflowExecutionStore,
    WorkflowStructuralRepository,
)
from execution.workflow_application import WorkflowApplicationService
from execution.batch_execution_store import BatchExecutionStore
from execution.batch_inputs import BatchInputService
from execution.batch_scheduler import BatchScheduler


class WorkflowServices:
    """Own the repositories and in-process managers for one application lifespan."""

    def __init__(
        self,
        database_path: str | Path = DEFAULT_DATABASE_PATH,
        execution_root: str | Path = DEFAULT_EXECUTION_ROOT,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.execution_root = Path(execution_root).resolve()
        self.repository = WorkflowStructuralRepository(self.database_path)
        self.model_repository = ModelProviderRepository(self.database_path)
        self.repository.initialize()
        self.model_repository.initialize()
        self.store = WorkflowExecutionStore(self.execution_root)
        self.manager = WorkflowExecutionManager(
            self.repository,
            self.model_repository,
            self.store,
        )
        self.batch_store = BatchExecutionStore(
            self.execution_root.parent / "batch_executions"
        )
        self.batch_inputs = BatchInputService(self.repository, self.batch_store)
        self.batch_scheduler = BatchScheduler(self.batch_store, self.manager)
        self.node_test_manager = NodeTestManager(
            self.model_repository,
        )
        self.application = WorkflowApplicationService(
            self.repository,
            self.manager,
            self.node_test_manager,
        )

    def shutdown(self, *, wait_seconds: float = 10) -> None:
        """Stop transient tests and persisted executions before releasing the app."""

        errors: list[str] = []
        for manager in (self.batch_scheduler, self.node_test_manager, self.manager):
            try:
                manager.shutdown(wait_seconds=wait_seconds)
            except Exception as exc:  # noqa: BLE001 - both managers must be attempted
                errors.append(str(exc))
        if errors:
            raise WorkflowExecutionError("；".join(errors))


def get_workflow_services(request: Request) -> WorkflowServices:
    """Resolve resources created for the current FastAPI application lifespan."""

    services = getattr(request.app.state, "workflow_services", None)
    if services is None:
        raise RuntimeError("Workflow 服务尚未进入应用生命周期")
    return services


WorkflowServicesDependency = Annotated[WorkflowServices, Depends(get_workflow_services)]
