import time
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import Workbook

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore
from execution.batch_inputs import BatchInputService
from execution.batch_scheduler import BatchScheduler
from execution.model_providers import ModelProviderRepository
from execution.node_structural_models import NODE_STRUCTURAL_ADAPTER
from execution.workflow_execution import WorkflowExecutionManager
from execution.workflow_execution_store import WorkflowExecutionStore
from execution.workflow_structural_models import WorkflowStructuralModel, WorkflowStructuralRepository


def _excel(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cases"
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def _node(node_type: str, **values):
    base = {"id": str(uuid4()), "type": node_type, "name": node_type, "description": ""}
    if node_type == "START":
        base["inputs"] = values.pop(
            "inputs", [{"name": "input", "type": "object", "value": {}}]
        )
    elif node_type == "SCRIPT":
        base.update(
            {
                "script": values.pop("script"),
                "execution": {
                    "timeout_seconds": 10,
                    "max_attempts": 0,
                    "retry_interval_seconds": 0,
                    "delay_seconds": 0,
                },
                "outputs": values.pop(
                    "outputs", [{"name": "answer", "type": "string", "source": "result"}]
                ),
            }
        )
    base.update(values)
    return NODE_STRUCTURAL_ADAPTER.validate_python(base)


def _services(tmp_path: Path, script: str):
    database = tmp_path / "database.sqlite3"
    repository = WorkflowStructuralRepository(database)
    start, worker, end = _node("START"), _node("SCRIPT", script=script), _node("END")
    workflow_id = str(uuid4())
    workflow = WorkflowStructuralModel(
        id=workflow_id,
        name="Batch workflow",
        description="",
        nodes=[
            {"node_id": node.id, "position_x": index * 200, "position_y": 0}
            for index, node in enumerate((start, worker, end))
        ],
        edges=[
            {"id": str(uuid4()), "source_node_id": start.id, "target_node_id": worker.id},
            {"id": str(uuid4()), "source_node_id": worker.id, "target_node_id": end.id},
        ],
    )
    repository.create(workflow, [start, worker, end])
    workflow_store = WorkflowExecutionStore(tmp_path / "workflow-runs")
    manager = WorkflowExecutionManager(
        repository, ModelProviderRepository(database), workflow_store
    )
    batch_store = BatchExecutionStore(tmp_path / "batch-runs")
    return workflow_id, repository, manager, batch_store


def _wait_batch(store: BatchExecutionStore, batch_id: str, timeout: float = 10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        batch = store.get(batch_id)
        if batch["status"] in {"SUCCESS", "COMPLETED_WITH_ERRORS", "INTERRUPTED"}:
            return batch
        time.sleep(0.03)
    raise AssertionError("Batch 未在时限内结束")


def test_batch_input_maps_columns_to_nested_start_values_and_freezes_source(tmp_path: Path):
    workflow_id, repository, _manager, store = _services(
        tmp_path, 'result = context["input"]["question"]'
    )
    source = tmp_path / "cases.xlsx"
    _excel(source, [["id", "question", "team"], ["C-1", "退款", "客服"]])
    service = BatchInputService(repository, store)

    batch = service.create(
        name="退款测试",
        source_path=source,
        sheet_name="Cases",
        workflow_id=workflow_id,
        case_id_column="id",
        mappings=[
            {"source": "question", "target": "input.question"},
            {"source": "team", "target": "input.team"},
        ],
        case_concurrency=2,
    )
    case = store.list_cases(batch["id"])[0]

    assert case["case_id"] == "C-1"
    assert case["start_inputs"] == {"input": {"question": "退款", "team": "客服"}}
    assert batch["input"]["sha256"]
    assert (store.batch_root(batch["id"]) / "input" / "source.xlsx").is_file()


def test_batch_input_rejects_duplicate_case_ids_and_conflicting_targets(tmp_path: Path):
    workflow_id, repository, _manager, store = _services(tmp_path, "result = 'ok'")
    source = tmp_path / "cases.xlsx"
    _excel(source, [["id", "question"], ["C-1", "a"], ["C-1", "b"]])
    service = BatchInputService(repository, store)
    common = dict(
        name="invalid",
        source_path=source,
        sheet_name="Cases",
        workflow_id=workflow_id,
        case_id_column="id",
        case_concurrency=1,
    )

    with pytest.raises(BatchExecutionError, match="目标冲突"):
        service.create(
            **common,
            mappings=[
                {"source": "question", "target": "input"},
                {"source": "id", "target": "input.id"},
            ],
        )
    with pytest.raises(BatchExecutionError, match="case_id 重复"):
        service.create(
            **common, mappings=[{"source": "question", "target": "input.question"}]
        )


def test_scheduler_isolates_failed_case_and_resume_skips_success(tmp_path: Path):
    script = (
        'question = context["input"]["question"]\n'
        'if question == "bad":\n    raise RuntimeError("bad case")\n'
        'result = question.upper()'
    )
    workflow_id, repository, manager, store = _services(tmp_path, script)
    source = tmp_path / "cases.xlsx"
    _excel(source, [["id", "question"], ["C-1", "good"], ["C-2", "bad"], ["C-3", "fine"]])
    batch = BatchInputService(repository, store).create(
        name="failure isolation",
        source_path=source,
        sheet_name="Cases",
        workflow_id=workflow_id,
        case_id_column="id",
        mappings=[{"source": "question", "target": "input.question"}],
        case_concurrency=2,
    )
    scheduler = BatchScheduler(store, manager, max_total_case_concurrency=2)

    scheduler.start(batch["id"])
    finished = _wait_batch(store, batch["id"])
    cases = {case["case_id"]: case for case in store.list_cases(batch["id"])}

    assert finished["status"] == "COMPLETED_WITH_ERRORS"
    assert {case_id: case["status"] for case_id, case in cases.items()} == {
        "C-1": "SUCCESS",
        "C-2": "FAILED",
        "C-3": "SUCCESS",
    }
    successful_execution_ids = {
        case_id: list(cases[case_id]["workflow_execution_ids"]) for case_id in ("C-1", "C-3")
    }

    scheduler.resume(batch["id"], retry_failed=True)
    _wait_batch(store, batch["id"])
    resumed = {case["case_id"]: case for case in store.list_cases(batch["id"])}
    assert resumed["C-1"]["workflow_execution_ids"] == successful_execution_ids["C-1"]
    assert resumed["C-3"]["workflow_execution_ids"] == successful_execution_ids["C-3"]
    assert len(resumed["C-2"]["workflow_execution_ids"]) == 2


def test_scheduler_cancel_stops_new_case_dispatch_and_marks_batch_interrupted(tmp_path: Path):
    workflow_id, repository, manager, store = _services(
        tmp_path, 'import time\ntime.sleep(5)\nresult = "done"'
    )
    source = tmp_path / "cases.xlsx"
    _excel(source, [["id", "question"], ["C-1", "one"], ["C-2", "two"]])
    batch = BatchInputService(repository, store).create(
        name="cancel",
        source_path=source,
        sheet_name="Cases",
        workflow_id=workflow_id,
        case_id_column="id",
        mappings=[{"source": "question", "target": "input.question"}],
        case_concurrency=1,
    )
    scheduler = BatchScheduler(store, manager, max_total_case_concurrency=1)
    scheduler.start(batch["id"])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if any(case["status"] == "RUNNING" for case in store.list_cases(batch["id"])):
            break
        time.sleep(0.03)

    assert scheduler.cancel(batch["id"])
    finished = _wait_batch(store, batch["id"])
    cases = store.list_cases(batch["id"])

    assert finished["status"] == "INTERRUPTED"
    assert {case["status"] for case in cases} == {"INTERRUPTED"}
    assert sum(len(case["workflow_execution_ids"]) for case in cases) == 1
