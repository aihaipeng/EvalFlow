import time
from pathlib import Path
from uuid import uuid4

import pytest

from execution.batch_execution_store import BatchExecutionError, BatchExecutionStore
from execution.batch_inputs import BatchInputService
from execution.batch_scheduler import BatchScheduler
from execution.model_providers import ModelProviderRepository
from execution.node_structural_models import NODE_STRUCTURAL_ADAPTER
from execution.test_sets import TestSetRepository as SetRepository
from execution.workflow_execution import WorkflowExecutionManager
from execution.workflow_execution_store import WorkflowExecutionStore
from execution.workflow_structural_models import WorkflowStructuralModel, WorkflowStructuralRepository


def _node(node_type: str, **values):
    base = {"id": str(uuid4()), "type": node_type, "name": node_type, "description": ""}
    if node_type == "START":
        base["inputs"] = values.pop("inputs", [{"name": "input", "type": "object", "value": {}}])
    elif node_type == "SCRIPT":
        base.update({
            "script": values.pop("script"),
            "execution": {"timeout_seconds": 10, "max_attempts": 0, "retry_interval_seconds": 0, "delay_seconds": 0},
            "outputs": values.pop("outputs", [{"name": "answer", "type": "string", "source": "result"}]),
        })
    base.update(values)
    return NODE_STRUCTURAL_ADAPTER.validate_python(base)


def _services(tmp_path: Path, script: str):
    database = tmp_path / "database.sqlite3"
    repository = WorkflowStructuralRepository(database)
    test_sets = SetRepository(database)
    test_sets.initialize()
    start, worker, end = _node("START"), _node("SCRIPT", script=script), _node("END")
    workflow_id = str(uuid4())
    workflow = WorkflowStructuralModel(
        id=workflow_id, name="Batch workflow", description="",
        nodes=[{"node_id": node.id, "position_x": index * 200, "position_y": 0} for index, node in enumerate((start, worker, end))],
        edges=[
            {"id": str(uuid4()), "source_node_id": start.id, "target_node_id": worker.id},
            {"id": str(uuid4()), "source_node_id": worker.id, "target_node_id": end.id},
        ],
    )
    repository.create(workflow, [start, worker, end])
    manager = WorkflowExecutionManager(repository, ModelProviderRepository(database), WorkflowExecutionStore(tmp_path / "workflow-runs"))
    batch_store = BatchExecutionStore(tmp_path / "batch-runs")
    return workflow_id, repository, test_sets, manager, batch_store


def _test_set(repository: SetRepository, rows: list[tuple[str, str]], *, columns=("case_name", "question")):
    return repository.create(
        name=f"测试集-{uuid4().hex[:8]}", description="", columns=list(columns),
        cases=[{"id": case_id, "values": {columns[0]: case_id, columns[1]: question}} for case_id, question in rows],
    )


def _wait_batch(store: BatchExecutionStore, batch_id: str, timeout: float = 10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        batch = store.get(batch_id)
        if batch["status"] in {"SUCCESS", "COMPLETED_WITH_ERRORS", "INTERRUPTED"}:
            return batch
        time.sleep(0.03)
    raise AssertionError("Batch 未在时限内结束")


def test_batch_input_injects_test_set_fields_and_freezes_snapshot(tmp_path: Path):
    workflow_id, repository, test_sets, _manager, store = _services(tmp_path, 'result = context["question"]')
    test_set = _test_set(test_sets, [("C-1", "退款")])
    service = BatchInputService(repository, test_sets, store)

    batch = service.create(
        name="退款测试", test_set_id=test_set.id, workflow_id=workflow_id,
        variables=[
            {"source": "TEST_SET", "key": "question", "value": "question", "type": "string"},
            {"source": "CUSTOM", "key": "body", "value": '{"kind":"case"}', "type": "object"},
        ],
        case_concurrency=2,
    )
    case = store.list_cases(batch["id"])[0]
    test_sets.update(test_set.id, name=test_set.name, description="", columns=["case_name", "question"], cases=[{"id": "C-1", "values": {"case_name": "C-1", "question": "已修改"}}])

    assert case["case_id"] == "C-1"
    assert case["row_number"] == 1
    assert case["start_inputs"] == {"question": "退款", "body": {"kind": "case"}}
    assert batch["input"]["test_set_id"] == test_set.id
    snapshot = BatchExecutionStore._read(store.batch_root(batch["id"]) / "input" / "snapshot.json")
    assert snapshot["cases"][0]["values"]["question"] == "退款"
    assert not list((store.batch_root(batch["id"]) / "input").glob("source.*"))


def test_batch_input_rejects_invalid_variable_config_and_keeps_case_ids(tmp_path: Path):
    workflow_id, repository, test_sets, _manager, store = _services(tmp_path, "result = 'ok'")
    test_set = _test_set(test_sets, [("C-1", "a"), ("C-2", "b")])
    service = BatchInputService(repository, test_sets, store)
    common = dict(name="invalid", test_set_id=test_set.id, workflow_id=workflow_id, case_concurrency=1)

    with pytest.raises(BatchExecutionError, match="key 不能重复"):
        service.create(**common, variables=[
            {"source": "TEST_SET", "key": "question", "value": "question", "type": "string"},
            {"source": "TEST_SET", "key": "question", "value": "case_name", "type": "string"},
        ])
    with pytest.raises(BatchExecutionError, match="测试集字段不存在"):
        service.create(**common, variables=[{"source": "TEST_SET", "key": "question", "value": "missing", "type": "string"}])

    batch = service.create(**common, variables=[{"source": "TEST_SET", "key": "question", "value": "question", "type": "string"}])
    assert [case["case_id"] for case in store.list_cases(batch["id"])] == ["C-1", "C-2"]


def test_scheduler_isolates_failed_case_and_resume_skips_success(tmp_path: Path):
    script = 'question = context["question"]\nif question == "bad":\n    raise RuntimeError("bad case")\nresult = question.upper()'
    workflow_id, repository, test_sets, manager, store = _services(tmp_path, script)
    test_set = _test_set(test_sets, [("C-1", "good"), ("C-2", "bad"), ("C-3", "fine")])
    batch = BatchInputService(repository, test_sets, store).create(
        name="failure isolation", test_set_id=test_set.id, workflow_id=workflow_id,
        variables=[{"source": "TEST_SET", "key": "question", "value": "question", "type": "string"}], case_concurrency=2,
    )
    scheduler = BatchScheduler(store, manager, max_total_case_concurrency=2)

    scheduler.start(batch["id"])
    finished = _wait_batch(store, batch["id"])
    cases = {case["case_id"]: case for case in store.list_cases(batch["id"])}
    assert finished["status"] == "COMPLETED_WITH_ERRORS"
    assert {case_id: case["status"] for case_id, case in cases.items()} == {"C-1": "SUCCESS", "C-2": "FAILED", "C-3": "SUCCESS"}
    successful = {case_id: list(cases[case_id]["workflow_execution_ids"]) for case_id in ("C-1", "C-3")}

    scheduler.resume(batch["id"], retry_failed=True)
    _wait_batch(store, batch["id"])
    resumed = {case["case_id"]: case for case in store.list_cases(batch["id"])}
    assert resumed["C-1"]["workflow_execution_ids"] == successful["C-1"]
    assert resumed["C-3"]["workflow_execution_ids"] == successful["C-3"]
    assert len(resumed["C-2"]["workflow_execution_ids"]) == 2


def test_scheduler_marks_case_failed_when_any_context_rule_fails(tmp_path: Path):
    workflow_id, repository, test_sets, manager, store = _services(tmp_path, 'result = context["question"].upper()')
    test_set = _test_set(test_sets, [("C-1", "good")])
    batch = BatchInputService(repository, test_sets, store).create(
        name="evaluation failure", test_set_id=test_set.id, workflow_id=workflow_id,
        variables=[{"source": "TEST_SET", "key": "question", "value": "question", "type": "string"}], case_concurrency=1,
        evaluation_rules=[
            {"result_path": "context.answer", "operator": "EQ", "expected_value": "DIFFERENT", "type": "string"},
            {"result_path": "context.answer", "operator": "EXISTS", "expected_value": "true", "type": "boolean"},
        ],
    )
    scheduler = BatchScheduler(store, manager, max_total_case_concurrency=1)
    scheduler.start(batch["id"])
    finished = _wait_batch(store, batch["id"])
    case = store.list_cases(batch["id"])[0]
    assert finished["status"] == "COMPLETED_WITH_ERRORS"
    assert case["status"] == "FAILED"
    assert case["execution_status"] == "SUCCESS"
    assert case["verdict"] == "FAIL"


def test_scheduler_cancel_stops_new_case_dispatch_and_marks_batch_interrupted(tmp_path: Path):
    workflow_id, repository, test_sets, manager, store = _services(tmp_path, 'import time\ntime.sleep(5)\nresult = "done"')
    test_set = _test_set(test_sets, [("C-1", "one"), ("C-2", "two")])
    batch = BatchInputService(repository, test_sets, store).create(
        name="cancel", test_set_id=test_set.id, workflow_id=workflow_id,
        variables=[{"source": "TEST_SET", "key": "question", "value": "question", "type": "string"}], case_concurrency=1,
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
