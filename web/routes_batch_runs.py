"""Batch Run API for database-backed test-set scheduling."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from execution.batch_execution_store import (
    BatchExecutionError,
    batch_case_result,
    batch_case_search_text,
)
from execution.case_evaluator import EvaluationRule
from execution.resource_names import next_copy_name
from web.workflow_services import WorkflowServicesDependency


router = APIRouter(prefix="/api/batch-runs", tags=["batch-runs"])


class _BatchApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchPreviewRequest(_BatchApiModel):
    test_set_id: str = Field(min_length=1)


class BatchPreviewSample(_BatchApiModel):
    case_id: str
    row_number: int
    values: dict[str, str]


class BatchPreviewResponse(_BatchApiModel):
    test_set_id: str
    test_set_name: str
    headers: list[str]
    total_rows: int
    sample_rows: list[BatchPreviewSample]


class BatchVariable(_BatchApiModel):
    source: Literal["CUSTOM", "TEST_SET"]
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=20000)
    type: Literal["string", "number", "integer", "boolean", "object", "array", "null"]


class BatchCreateRequest(_BatchApiModel):
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    test_set_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    variables: list[BatchVariable] = Field(min_length=1, max_length=100)
    case_concurrency: int = Field(default=1, ge=1, le=32)
    failure_retry_count: int = Field(default=0, ge=0, le=10)
    call_order: Literal["SEQUENTIAL", "REVERSE", "RANDOM"] = "SEQUENTIAL"
    evaluation_rules: list[EvaluationRule] = Field(default_factory=list, max_length=50)
    case_display_column: str | None = Field(default=None, max_length=200)
    rule_display_column: str | None = Field(default=None, max_length=200)


class BatchResumeRequest(_BatchApiModel):
    retry_failed: bool = False


class BatchStartRequest(_BatchApiModel):
    mode: Literal["FULL", "RESUME", "RETRY_FAILED"] = "FULL"


class BatchScheduleRequest(_BatchApiModel):
    enabled: bool = True
    cadence: Literal["ONCE", "DAILY", "WEEKLY", "MONTHLY"] = "DAILY"
    run_at: str = Field(default="", max_length=40)
    run_time: str = Field(default="09:00", max_length=16)
    weekdays: list[Literal["0", "1", "2", "3", "4", "5", "6"]] = Field(
        default_factory=lambda: ["1", "2", "3", "4", "5"], max_length=7
    )
    month_day: int = Field(default=1, ge=1, le=31)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=100)
    overlap_policy: Literal["SKIP", "QUEUE"] = "SKIP"


class BatchEnvelope(_BatchApiModel):
    batch: dict[str, Any]


class BatchListEnvelope(_BatchApiModel):
    batches: list[dict[str, Any]]


class BatchCaseListEnvelope(_BatchApiModel):
    batch: dict[str, Any]
    cases: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_all: int
    summary: dict[str, int]


class BatchRoundListEnvelope(_BatchApiModel):
    rounds: list[dict[str, Any]]


class BatchHistoryItem(_BatchApiModel):
    id: str
    batch_id: str
    execution_round_id: str | None
    workflow_id: str
    test_set_name: str
    workflow_name: str
    total_cases: int
    executed_cases: int
    passed_cases: int
    started_at: str
    finished_at: str
    created_at: str


class BatchHistoryListEnvelope(_BatchApiModel):
    history: list[BatchHistoryItem]


class BatchCopyNameEnvelope(_BatchApiModel):
    name: str


def _error(exc: Exception) -> None:
    raise HTTPException(400, str(exc)) from exc


def _batch_case_result(case: dict[str, Any]) -> str | None:
    return batch_case_result(case)


def _batch_list_activity_times(
    batch: dict[str, Any], cases: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    batch_started_at = batch.get("started_at")
    batch_finished_at = batch.get("finished_at")
    case_started_at = max(
        (case.get("started_at") for case in cases if case.get("started_at")),
        default=None,
    )
    has_later_case_run = bool(
        case_started_at
        and (
            not batch_started_at
            or (batch_finished_at and case_started_at > batch_finished_at)
        )
    )
    started_at = case_started_at if has_later_case_run else batch_started_at
    has_active_case = any(
        case.get("status") == "RUNNING" or case.get("execution_status") == "RUNNING"
        for case in cases
    )
    if has_active_case:
        return started_at, None
    case_finished_at = max(
        (case.get("finished_at") for case in cases if case.get("finished_at")),
        default=None,
    )
    finished_at = case_finished_at if has_later_case_run else (
        batch_finished_at or case_finished_at
    )
    return started_at, finished_at


def _case_search_text(case: dict[str, Any]) -> str:
    return batch_case_search_text(case)


def _batch_case_list_summary(batch: dict[str, Any]) -> dict[str, Any]:
    input_snapshot = batch.get("input") if isinstance(batch.get("input"), dict) else {}
    workflow = batch.get("workflow") if isinstance(batch.get("workflow"), dict) else {}
    return {
        "id": batch["id"],
        "name": batch.get("name", ""),
        "status": batch.get("status"),
        "execution_mode": batch.get("execution_mode"),
        "execution_round_id": batch.get("execution_round_id"),
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at"),
        "input": {
            "test_set_id": input_snapshot.get("test_set_id"),
            "test_set_name": input_snapshot.get("test_set_name"),
            "columns": input_snapshot.get("columns", []),
            "display_columns": input_snapshot.get("display_columns", {}),
        },
        "workflow": {"id": workflow.get("id"), "name": workflow.get("name")},
    }


@router.post("/preview", response_model=BatchPreviewResponse)
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
            description=body.description,
            test_set_id=body.test_set_id,
            workflow_id=body.workflow_id,
            variables=[variable.model_dump() for variable in body.variables],
            case_concurrency=body.case_concurrency,
            failure_retry_count=body.failure_retry_count,
            call_order=body.call_order,
            evaluation_rules=[rule.model_dump(mode="json") for rule in body.evaluation_rules],
            case_display_column=body.case_display_column,
            rule_display_column=body.rule_display_column,
        )
    except (BatchExecutionError, ValueError) as exc:
        _error(exc)
    return BatchEnvelope(batch=batch)


@router.put("/{batch_id}", response_model=BatchEnvelope)
def update_batch(
    batch_id: str,
    body: BatchCreateRequest,
    services: WorkflowServicesDependency,
) -> BatchEnvelope:
    try:
        batch = services.batch_inputs.update(
            batch_id,
            name=body.name,
            description=body.description,
            test_set_id=body.test_set_id,
            workflow_id=body.workflow_id,
            variables=[variable.model_dump() for variable in body.variables],
            case_concurrency=body.case_concurrency,
            failure_retry_count=body.failure_retry_count,
            call_order=body.call_order,
            evaluation_rules=[rule.model_dump(mode="json") for rule in body.evaluation_rules],
            case_display_column=body.case_display_column,
            rule_display_column=body.rule_display_column,
        )
    except (BatchExecutionError, ValueError) as exc:
        _error(exc)
    return BatchEnvelope(batch=batch)


@router.get("", response_model=BatchListEnvelope)
def list_batches(services: WorkflowServicesDependency) -> BatchListEnvelope:
    batches = []
    current_test_sets: dict[str, Any] = {}
    current_workflows: dict[str, Any] = {}
    schedules = {
        schedule["batch_id"]: schedule for schedule in services.batch_schedules.list()
    }
    for batch in services.batch_store.list():
        summary = {key: value for key, value in batch.items() if key != "workflow"}
        configuration = batch.get("configuration") or {}
        summary["name"] = configuration.get("name", batch["name"])
        summary["input"] = dict(batch["input"])
        test_set_id = configuration.get(
            "test_set_id", batch["input"]["test_set_id"]
        )
        test_set_name = configuration.get(
            "test_set_name", batch["input"]["test_set_name"]
        )
        if test_set_id not in current_test_sets:
            current_test_sets[test_set_id] = services.test_sets.get(test_set_id)
        current_test_set = current_test_sets[test_set_id]
        summary["input"]["test_set_id"] = test_set_id
        summary["input"]["test_set_name"] = (
            current_test_set.name if current_test_set else test_set_name
        )
        workflow_id = configuration.get("workflow_id", batch["workflow"]["id"])
        workflow_name = configuration.get(
            "workflow_name", batch["workflow"]["name"]
        )
        if workflow_id not in current_workflows:
            current_workflows[workflow_id] = services.repository.get(workflow_id)
        current_workflow = current_workflows[workflow_id]
        summary["workflow"] = {
            "id": workflow_id,
            "name": current_workflow.workflow.name if current_workflow else workflow_name,
        }
        summary["schedule"] = schedules.get(batch["id"])
        if batch.get("status") != "RUNNING":
            cases = services.batch_store.list_cases(batch["id"])
            summary["started_at"], summary["finished_at"] = _batch_list_activity_times(
                batch, cases
            )
        batches.append(summary)
    return BatchListEnvelope(batches=batches)


@router.get("/{batch_id}", response_model=BatchEnvelope)
def get_batch(
    batch_id: str,
    services: WorkflowServicesDependency,
    round_id: str | None = Query(default=None),
) -> BatchEnvelope:
    try:
        batch = services.batch_store.get_round(batch_id, round_id)
    except BatchExecutionError as exc:
        _error(exc)
    if batch is None:
        raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
    return BatchEnvelope(batch=batch)


@router.get("/{batch_id}/copy-name", response_model=BatchCopyNameEnvelope)
def get_batch_copy_name(
    batch_id: str, services: WorkflowServicesDependency
) -> BatchCopyNameEnvelope:
    """按全部已保存任务名称计算可用的拷贝任务名称。"""

    source = services.batch_store.get(batch_id)
    if source is None:
        raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
    existing = services.batch_store.list()
    existing_names = {
        (item.get("configuration") or {}).get("name", item.get("name", ""))
        for item in existing
    }
    source_name = (source.get("configuration") or {}).get(
        "name", source.get("name", "")
    )
    try:
        name = next_copy_name(source_name, existing_names)
    except ValueError as exc:
        _error(exc)
    return BatchCopyNameEnvelope(name=name)


@router.get("/{batch_id}/rounds", response_model=BatchRoundListEnvelope)
def list_batch_rounds(
    batch_id: str, services: WorkflowServicesDependency
) -> BatchRoundListEnvelope:
    try:
        rounds = services.batch_store.list_rounds(batch_id)
    except BatchExecutionError as exc:
        _error(exc)
    return BatchRoundListEnvelope(
        rounds=[
            {
                "id": item["execution_round_id"],
                "number": item.get("execution_round_number", 1),
                "status": item["status"],
                "started_at": item.get("started_at"),
                "finished_at": item.get("finished_at"),
                "summary": item.get("summary", {}),
            }
            for item in rounds
        ]
    )


@router.get("/{batch_id}/history", response_model=BatchHistoryListEnvelope)
def list_batch_history(
    batch_id: str, services: WorkflowServicesDependency
) -> BatchHistoryListEnvelope:
    if services.batch_store.get(batch_id) is None:
        raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
    return BatchHistoryListEnvelope(
        history=services.batch_history.list_recent(batch_id, limit=10)
    )


@router.delete("/{batch_id}", response_model=BatchEnvelope)
def delete_batch(batch_id: str, services: WorkflowServicesDependency) -> BatchEnvelope:
    try:
        batch = services.batch_store.delete(batch_id)
        services.batch_history.delete_batch(batch_id)
        services.batch_schedules.delete(batch_id)
        services.batch_schedule_manager.refresh(batch_id)
        return BatchEnvelope(batch=batch)
    except BatchExecutionError as exc:
        _error(exc)


@router.get("/{batch_id}/schedule")
def get_batch_schedule(
    batch_id: str, services: WorkflowServicesDependency
) -> dict[str, Any]:
    if services.batch_store.get(batch_id) is None:
        raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
    return {"schedule": services.batch_schedules.get(batch_id)}


@router.put("/{batch_id}/schedule")
def save_batch_schedule(
    batch_id: str,
    body: BatchScheduleRequest,
    services: WorkflowServicesDependency,
) -> dict[str, Any]:
    if services.batch_store.get(batch_id) is None:
        raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
    try:
        if body.enabled:
            services.batch_inputs.validate_execution(batch_id)
        schedule = services.batch_schedules.save(batch_id, body.model_dump())
        services.batch_schedule_manager.refresh(batch_id)
    except (BatchExecutionError, ValueError) as exc:
        _error(exc)
    return {"schedule": schedule}


@router.post("/{batch_id}/start", response_model=BatchEnvelope, status_code=202)
def start_batch(
    batch_id: str,
    services: WorkflowServicesDependency,
    body: BatchStartRequest | None = None,
) -> BatchEnvelope:
    try:
        if services.batch_store.get(batch_id) is None:
            raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
        if body is None:
            current = services.batch_store.get(batch_id)
            mode = (
                "RESUME"
                if current
                and services.batch_store.has_execution(current)
                and current.get("status") not in {"SUCCESS", "COMPLETED_WITH_ERRORS"}
                else "FULL"
            )
        else:
            mode = body.mode
        return BatchEnvelope(batch=services.batch_scheduler.start(batch_id, mode=mode))
    except BatchExecutionError as exc:
        _error(exc)


@router.post("/{batch_id}/cancel", response_model=BatchEnvelope)
def cancel_batch(batch_id: str, services: WorkflowServicesDependency) -> BatchEnvelope:
    try:
        batch = services.batch_store.get(batch_id)
        if batch is None:
            raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
        if not services.batch_scheduler.cancel(batch_id):
            raise BatchExecutionError("只有运行中的任务可以停止")
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
    round_id: str | None = Query(default=None),
    result: Literal["Pass", "Failed", "Error"] | None = Query(default=None),
    state: Literal["Running", "Pending"] | None = Query(default=None),
    q: str = Query(default="", max_length=200),
) -> BatchCaseListEnvelope:
    try:
        batch = services.batch_store.get_round(batch_id, round_id)
        if batch is None:
            if round_id is None:
                raise HTTPException(404, f"Batch Execution 不存在: {batch_id}")
            raise HTTPException(404, f"执行轮次不存在: {round_id}")
        query = services.batch_store.query_cases(
            batch_id,
            round_id,
            page=page,
            page_size=page_size,
            result=result,
            state=state,
            search=q,
        )
    except BatchExecutionError as exc:
        _error(exc)
    return BatchCaseListEnvelope(
        batch=_batch_case_list_summary(batch),
        cases=query["cases"],
        total=query["total"],
        page=page,
        page_size=page_size,
        total_all=query["total_all"],
        summary=query["summary"],
    )


@router.get("/{batch_id}/cases/{case_run_id}")
def get_batch_case(
    batch_id: str,
    case_run_id: str,
    services: WorkflowServicesDependency,
    round_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        case = services.batch_store.get_case(batch_id, case_run_id, round_id)
    except BatchExecutionError as exc:
        _error(exc)
    if case is None:
        raise HTTPException(404, f"Case Run 不存在: {case_run_id}")
    return {"case": case}


@router.post("/{batch_id}/cases/{case_run_id}/start")
def start_batch_case(batch_id: str, case_run_id: str, services: WorkflowServicesDependency) -> dict[str, Any]:
    try:
        return {"case": services.batch_scheduler.start_case(batch_id, case_run_id)}
    except BatchExecutionError as exc:
        _error(exc)


@router.post("/{batch_id}/cases/{case_run_id}/cancel")
def cancel_batch_case(batch_id: str, case_run_id: str, services: WorkflowServicesDependency) -> dict[str, Any]:
    raise HTTPException(405, "单条用例执行不支持中断")
