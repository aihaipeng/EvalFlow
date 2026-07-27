"""Batch Run API for Excel-backed Workflow scheduling."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from execution.batch_execution_store import BatchExecutionError
from execution.case_evaluator import EvaluationRule
from web.files import get_existing_input_path
from web.workflow_services import WorkflowServicesDependency


router = APIRouter(prefix="/api/batch-runs", tags=["batch-runs"])


class _BatchApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchPreviewRequest(_BatchApiModel):
    filename: str = Field(min_length=1)
    sheet_name: str = Field(min_length=1)
    header_mode: Literal["AUTO", "HEADER", "DATA"] = "AUTO"


class BatchMapping(_BatchApiModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)


class BatchCreateRequest(_BatchApiModel):
    name: str = Field(default="", max_length=200)
    filename: str = Field(min_length=1)
    sheet_name: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    case_id_column: str = Field(min_length=1)
    mappings: list[BatchMapping] = Field(min_length=1)
    case_concurrency: int = Field(default=1, ge=1, le=32)
    header_mode: Literal["AUTO", "HEADER", "DATA"] = "AUTO"
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
        snapshot = services.batch_inputs.preview(
            get_existing_input_path(body.filename), body.sheet_name, body.header_mode
        )
    except (BatchExecutionError, FileNotFoundError, ValueError) as exc:
        _error(exc)
    return {
        "filename": body.filename,
        "sheet_name": body.sheet_name,
        "headers": list(snapshot.headers),
        "header_mode": snapshot.header_mode,
        "total_rows": len(snapshot.rows),
        "sample_rows": [
            {"row_number": row.row_number, "values": row.values}
            for row in snapshot.rows[:20]
        ],
    }


@router.post("", response_model=BatchEnvelope, status_code=201)
def create_batch(
    body: BatchCreateRequest, services: WorkflowServicesDependency
) -> BatchEnvelope:
    try:
        batch = services.batch_inputs.create(
            name=body.name,
            source_path=get_existing_input_path(body.filename),
            sheet_name=body.sheet_name,
            workflow_id=body.workflow_id,
            case_id_column=body.case_id_column,
            mappings=[mapping.model_dump() for mapping in body.mappings],
            case_concurrency=body.case_concurrency,
            header_mode=body.header_mode,
            evaluation_rules=[rule.model_dump(mode="json") for rule in body.evaluation_rules],
        )
    except (BatchExecutionError, FileNotFoundError, ValueError) as exc:
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
