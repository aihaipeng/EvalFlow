"""Database-backed test-set management API."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from execution.test_sets import (
    TestSetNameConflictError,
    TestSetRecord,
    TestSetRepositoryError,
    TestSetSummary,
)
from web.workflow_services import WorkflowServicesDependency

router = APIRouter(prefix="/api/test-sets", tags=["test-sets"])


class TestCaseWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    values: dict[str, str]


class TestSetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    columns: list[str] = Field(min_length=1)
    cases: list[TestCaseWrite] = Field(default_factory=list)


class TestSetUpdateRequest(TestSetCreateRequest):
    pass


def _case_payload(case: TestCaseWrite) -> dict:
    return {"id": case.id, "values": case.values}


def _record_payload(record: TestSetRecord) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "columns": [column.key for column in record.columns],
        "cases": [
            {"id": case.id, "position": case.position, "values": case.values}
            for case in record.cases
        ],
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _summary_payload(summary: TestSetSummary) -> dict:
    return asdict(summary)


def _handle_error(error: TestSetRepositoryError) -> None:
    if isinstance(error, TestSetNameConflictError):
        raise HTTPException(409, str(error)) from error
    if str(error) == "测试集不存在":
        raise HTTPException(404, str(error)) from error
    raise HTTPException(400, str(error)) from error


@router.get("")
def list_test_sets(
    services: WorkflowServicesDependency,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    name_query: str = Query(""),
) -> dict:
    summaries, total = services.test_sets.list(
        page=page, page_size=page_size, name_query=name_query
    )
    return {
        "items": [_summary_payload(summary) for summary in summaries],
        "metrics": services.test_sets.metrics(),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=201)
def create_test_set(
    body: TestSetCreateRequest, services: WorkflowServicesDependency
) -> dict:
    try:
        record = services.test_sets.create(
            name=body.name,
            description=body.description,
            columns=body.columns,
            cases=[_case_payload(case) for case in body.cases],
        )
    except TestSetRepositoryError as error:
        _handle_error(error)
    return {"test_set": _record_payload(record)}


@router.get("/{test_set_id}")
def get_test_set(test_set_id: str, services: WorkflowServicesDependency) -> dict:
    record = services.test_sets.get(test_set_id)
    if record is None:
        raise HTTPException(404, "测试集不存在")
    return {"test_set": _record_payload(record)}


@router.put("/{test_set_id}")
def update_test_set(
    test_set_id: str,
    body: TestSetUpdateRequest,
    services: WorkflowServicesDependency,
) -> dict:
    try:
        record = services.test_sets.update(
            test_set_id,
            name=body.name,
            description=body.description,
            columns=body.columns,
            cases=[_case_payload(case) for case in body.cases],
        )
    except TestSetRepositoryError as error:
        _handle_error(error)
    return {"test_set": _record_payload(record)}


@router.delete("/{test_set_id}")
def delete_test_set(test_set_id: str, services: WorkflowServicesDependency) -> dict:
    if not services.test_sets.delete(test_set_id):
        raise HTTPException(404, "测试集不存在")
    return {"deleted": True, "id": test_set_id}
