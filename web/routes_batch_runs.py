"""Batch Run API for database-backed test-set scheduling."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from execution.batch_execution_store import BatchExecutionError
from execution.case_evaluator import EvaluationRule
from web.workflow_services import WorkflowServicesDependency


router = APIRouter(prefix="/api/batch-runs", tags=["batch-runs"])


class _BatchApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchPreviewRequest(_BatchApiModel):
    test_set_id: str = Field(min_length=1)


class BatchVariable(_BatchApiModel):
    source: Literal["CUSTOM", "TEST_SET"]
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=20000)
    type: Literal["string", "number", "integer", "boolean", "object", "array", "null"]


class BatchCreateRequest(_BatchApiModel):
    name: str = Field(default="", max_length=200)
    test_set_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    variables: list[BatchVariable] = Field(min_length=1, max_length=100)
    case_concurrency: int = Field(default=1, ge=1, le=32)
    evaluation_rules: list[EvaluationRule] = Field(default_factory=list, max_length=50)


class BatchResumeRequest(_BatchApiModel):
    retry_failed: bool = False


class BatchEnvelope(_BatchApiModel):
    batch: dict[str, Any]


class BatchListEnvelope(_BatchApiModel):
    batches: list[dict[str, Any]]


class BatchCaseListEnvelope(_BatchApiModel):
    cases: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


def _error(exc: Exception) -> None:
    raise HTTPException(400, str(exc)) from exc


@router.post("/preview")
def preview_batch_input(
    body: BatchPreviewRequest, services: WorkflowServicesDependency
) -> dict[str, Any]:
    try:
        test_set = services.batch_inputs.preview(body.test_set_id)
    except (BatchExecutionError, ValueError) as exc:
        _error(exc)
    return {
        "test_set_id": test_set.id,
        "test_set_name": test_set.name,
        "headers": [column.key for column in test_set.columns],
        "total_rows": len(test_set.cases),
        "sample_rows": [
            {
                "case_id": case.id,
                "row_number": case.position + 1,
                "values": case.values,
            }
            for case in test_set.cases[:20]
        ],
    }


@router.post("", response_model=BatchEnvelope, status_code=201)
def create_batch(
    body: BatchCreateRequest, services: WorkflowServicesDependency
) -> BatchEnvelope:
    try:
        batch = services.batch_inputs.create(
            name=body.name,
            test_set_id=body.test_set_id,
            workflow_id=body.workflow_id,
            variables=[variable.model_dump() for variable in body.variables],
            case_concurrency=body.case_concurrency,
            evaluation_rules=[rule.model_dump(mode="json") for rule in body.evaluation_rules],
        )
    except (BatchExecutionError, ValueError) as exc:
        _error(exc)
    return BatchEnvelope(batch=batch)


@router.get("", response_model=BatchListEnvelope)
def list_batches(services: WorkflowServicesDependency) -> BatchListEnvelope:
    batches = []
    for batch in services.batch_store.list():
        summary = {key: value for key, value in batch.items() if key != "workflow"}
        summary["workflow"] = {
            "id": batch["workflow"]["id"], "name": batch["workflow"]["name"]
        }
        batches.append(summary)
    return BatchListEnvelope(batches=batches)


@router.get("/{batch_id}", response_model=BatchEnvelope)
def get_batch(batch_id: str, services: WorkflowServicesDependency) -> BatchEnvelope:
    try:
        batch = services.batch_store.get(batch_id)
    except BatchExecutionError as exc:
        _error(exc)
    if batch is None:
        raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
    return BatchEnvelope(batch=batch)


@router.delete("/{batch_id}", response_model=BatchEnvelope)
def delete_batch(batch_id: str, services: WorkflowServicesDependency) -> BatchEnvelope:
    try:
        return BatchEnvelope(batch=services.batch_store.delete(batch_id))
    except BatchExecutionError as exc:
        _error(exc)


@router.post("/{batch_id}/start", response_model=BatchEnvelope, status_code=202)
def start_batch(batch_id: str, services: WorkflowServicesDependency) -> BatchEnvelope:
    try:
        return BatchEnvelope(batch=services.batch_scheduler.start(batch_id))
    except BatchExecutionError as exc:
        _error(exc)


@router.post("/{batch_id}/cancel", response_model=BatchEnvelope)
def cancel_batch(batch_id: str, services: WorkflowServicesDependency) -> BatchEnvelope:
    try:
        batch = services.batch_store.get(batch_id)
        if batch is None:
            raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
        services.batch_scheduler.cancel(batch_id)
        return BatchEnvelope(batch=services.batch_store.get(batch_id) or batch)
    except BatchExecutionError as exc:
        _error(exc)


@router.post("/{batch_id}/resume", response_model=BatchEnvelope, status_code=202)
def resume_batch(
    batch_id: str,
    body: BatchResumeRequest,
    services: WorkflowServicesDependency,
) -> BatchEnvelope:
    try:
        return BatchEnvelope(
            batch=services.batch_scheduler.resume(
                batch_id, retry_failed=body.retry_failed
            )
        )
    except BatchExecutionError as exc:
        _error(exc)


@router.get("/{batch_id}/cases", response_model=BatchCaseListEnvelope)
def list_batch_cases(
    batch_id: str,
    services: WorkflowServicesDependency,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> BatchCaseListEnvelope:
    try:
        if services.batch_store.get(batch_id) is None:
            raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
        cases = services.batch_store.list_cases(batch_id)
    except BatchExecutionError as exc:
        _error(exc)
    start = (page - 1) * page_size
    return BatchCaseListEnvelope(
        cases=cases[start : start + page_size],
        total=len(cases),
        page=page,
        page_size=page_size,
    )


@router.get("/{batch_id}/cases/{case_run_id}")
def get_batch_case(
    batch_id: str,
    case_run_id: str,
    services: WorkflowServicesDependency,
) -> dict[str, Any]:
    try:
        case = services.batch_store.get_case(batch_id, case_run_id)
    except BatchExecutionError as exc:
        _error(exc)
    if case is None:
        raise HTTPException(404, f"Case Run 不存在: {case_run_id}")
    return {"case": case}
