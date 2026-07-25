"""Workflow CRUD and run-query API for the new Workflow contract."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from execution.targets import DEFAULT_DATABASE_PATH
from execution.workflow_contract import WorkflowDefinition
from execution.workflow_adapters import WorkflowNodeAdapter
from execution.workflow_engine import WorkflowExecutor
from execution.workflows import (
    NodeRunRecord,
    WorkflowRecord,
    WorkflowRepository,
    WorkflowRepositoryError,
    WorkflowRunRecord,
)


router = APIRouter(prefix="/api/workflows", tags=["workflows"])
DATABASE_PATH = DEFAULT_DATABASE_PATH
_repository_instance: WorkflowRepository | None = None
_repository_path: Path | None = None


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowEnvelope(_StrictModel):
    workflow: WorkflowRecord


class WorkflowListEnvelope(_StrictModel):
    workflows: list[WorkflowRecord]


class WorkflowRunListEnvelope(_StrictModel):
    runs: list[WorkflowRunRecord]


class NodeRunListEnvelope(_StrictModel):
    runs: list[NodeRunRecord]


class WorkflowRunEnvelope(_StrictModel):
    run: WorkflowRunRecord


_active_runs: dict[str, asyncio.Task[WorkflowRunRecord]] = {}
_active_workflow_runs: dict[str, str] = {}


def repository() -> WorkflowRepository:
    global _repository_instance, _repository_path
    path = Path(DATABASE_PATH).resolve()
    if _repository_instance is None or _repository_path != path:
        _repository_instance = WorkflowRepository(path)
        _repository_path = path
    return _repository_instance


@router.get("", response_model=WorkflowListEnvelope)
def list_workflows() -> WorkflowListEnvelope:
    return WorkflowListEnvelope(workflows=repository().list_workflows())


@router.post("", response_model=WorkflowEnvelope)
def create_workflow(definition: WorkflowDefinition) -> WorkflowEnvelope:
    try:
        record = repository().create_workflow(WorkflowRecord.model_validate(definition.model_dump(mode="json")))
    except WorkflowRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkflowEnvelope(workflow=record)


@router.get("/{workflow_id}", response_model=WorkflowEnvelope)
def get_workflow(workflow_id: str) -> WorkflowEnvelope:
    record = repository().get_workflow(workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowEnvelope(workflow=record)


@router.put("/{workflow_id}", response_model=WorkflowEnvelope)
def update_workflow(workflow_id: str, definition: WorkflowDefinition) -> WorkflowEnvelope:
    if workflow_id != definition.workflow_id:
        raise HTTPException(status_code=422, detail="Workflow id does not match path")
    existing = repository().get_workflow(workflow_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    record = WorkflowRecord.model_validate(
        {**definition.model_dump(mode="json"), "created_at": existing.created_at}
    )
    return WorkflowEnvelope(workflow=repository().update_workflow(record))


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(workflow_id: str) -> Response:
    try:
        deleted = repository().delete_workflow(workflow_id)
    except WorkflowRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return Response(status_code=204)


@router.get("/{workflow_id}/runs", response_model=WorkflowRunListEnvelope)
def list_workflow_runs(workflow_id: str) -> WorkflowRunListEnvelope:
    if repository().get_workflow(workflow_id) is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowRunListEnvelope(runs=repository().list_workflow_runs(workflow_id))


@router.post("/{workflow_id}/runs", response_model=WorkflowRunEnvelope, status_code=202)
async def start_workflow_run(workflow_id: str) -> WorkflowRunEnvelope:
    workflow = repository().get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    active_id = _active_workflow_runs.get(workflow_id)
    if active_id and active_id in _active_runs and not _active_runs[active_id].done():
        raise HTTPException(status_code=409, detail="Workflow already has an active run")
    run_id = str(uuid4())
    executor = WorkflowExecutor(repository(), WorkflowNodeAdapter(DATABASE_PATH))
    task = asyncio.create_task(executor.run(workflow, run_id=run_id))
    _active_runs[run_id] = task
    _active_workflow_runs[workflow_id] = run_id

    def cleanup(_task):
        _active_runs.pop(run_id, None)
        if _active_workflow_runs.get(workflow_id) == run_id:
            _active_workflow_runs.pop(workflow_id, None)

    task.add_done_callback(cleanup)
    await asyncio.sleep(0)
    record = repository().get_workflow_run(run_id)
    if record is None:
        try:
            record = await task
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    return WorkflowRunEnvelope(run=record)


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunEnvelope)
def get_workflow_run(workflow_id: str, run_id: str) -> WorkflowRunEnvelope:
    record = repository().get_workflow_run(run_id)
    if record is None or record.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="WorkflowRun not found")
    return WorkflowRunEnvelope(run=record)


@router.post("/{workflow_id}/runs/{run_id}/cancel", response_model=WorkflowRunEnvelope)
async def cancel_workflow_run(workflow_id: str, run_id: str) -> WorkflowRunEnvelope:
    record = repository().get_workflow_run(run_id)
    if record is None or record.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="WorkflowRun not found")
    task = _active_runs.get(run_id)
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    current = repository().get_workflow_run(run_id)
    return WorkflowRunEnvelope(run=current or record)


@router.get("/{workflow_id}/runs/{run_id}/nodes", response_model=NodeRunListEnvelope)
def list_node_runs(workflow_id: str, run_id: str) -> NodeRunListEnvelope:
    workflow_run = repository().get_workflow_run(run_id)
    if workflow_run is None or workflow_run.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="WorkflowRun not found")
    return NodeRunListEnvelope(runs=repository().list_node_runs(run_id))
