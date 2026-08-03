import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

import execution.workflow_execution as workflow_execution_module
import execution.workflow_execution_control as workflow_execution_control_module
import execution.workflow_execution_store as workflow_execution_store_module
import execution.workflow_llm_runner as workflow_llm_runner_module
import execution.workflow_node_runner_base as workflow_node_runner_base_module

from execution.model_providers import ModelProviderRecord, ModelProviderRepository
from execution.node_structural_models import NODE_STRUCTURAL_ADAPTER
from execution.workflow_execution import (
    NodeTestManager,
    WorkflowExecutionError,
    WorkflowExecutionManager,
    WorkflowExecutionStore,
)
from execution.workflow_node_executor import WorkflowNodeExecutor
from execution.workflow_http_runner import HttpNodeRunner
from execution.workflow_structural_models import (
    WorkflowStructuralModel,
    WorkflowStructuralRepository,
)


def wait_for_terminal(store, workflow_id, execution_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = store.get_workflow(workflow_id, execution_id)
        if document["status"] in {"SUCCESS", "FAILED", "INTERRUPTED"}:
            return document
        time.sleep(0.03)
    raise AssertionError("Workflow Execution 未在测试时限内结束")


def test_execution_runtime_is_split_by_responsibility():
    scheduler_path = Path(workflow_execution_module.__file__)

    assert len(scheduler_path.read_text(encoding="utf-8").splitlines()) <= 400
    assert WorkflowExecutionStore.__module__ == "execution.workflow_execution_store"
    assert WorkflowNodeExecutor.__module__ == "execution.workflow_node_executor"
    assert NodeTestManager.__module__ == "execution.workflow_node_tests"
    assert not hasattr(WorkflowExecutionManager, "_execute_script")


def test_worker_registered_after_global_cancel_is_pre_cancelled(monkeypatch):
    interrupted_workers = []
    monkeypatch.setattr(
        workflow_execution_control_module,
        "interrupt_tool_run",
        lambda worker_id: interrupted_workers.append(worker_id),
    )
    controller = workflow_execution_module._ExecutionController()
    controller.user_cancel.set()

    controller.add_worker("late-worker")

    assert interrupted_workers == ["late-worker"]


def test_workflow_manager_shutdown_rejects_new_executions(tmp_path):
    repository = WorkflowStructuralRepository(tmp_path / "workflow.sqlite3")
    manager, _store = make_manager(tmp_path, repository)

    manager.shutdown()
    manager.shutdown()

    with pytest.raises(WorkflowExecutionError, match="Manager 已关闭"):
        manager.start(str(uuid4()))


def test_node_test_manager_shutdown_rejects_new_tests(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    manager = NodeTestManager(
        ModelProviderRepository(database),
    )

    manager.shutdown()
    manager.shutdown()

    with pytest.raises(WorkflowExecutionError, match="Manager 已关闭"):
        manager.start(str(uuid4()), make_node("SCRIPT"), {})


def make_node(node_type, *, node_id=None, name=None, **overrides):
    node_id = node_id or str(uuid4())
    base = {"id": node_id, "type": node_type, "name": name or node_type, "description": ""}
    if node_type == "START":
        base["inputs"] = overrides.pop("inputs", [])
    elif node_type == "SCRIPT":
        base.update(
            {
                "script": overrides.pop("script", "result = None"),
                "execution": overrides.pop(
                    "execution",
                    {
                        "timeout_seconds": 5,
                        "max_attempts": 0,
                        "retry_interval_seconds": 0,
                        "delay_seconds": 0,
                    },
                ),
                "outputs": overrides.pop("outputs", []),
            }
        )
    base.update(overrides)
    return NODE_STRUCTURAL_ADAPTER.validate_python(base)


def create_workflow(database, nodes, edge_pairs, *, name="执行测试"):
    workflow_id = str(uuid4())
    workflow = WorkflowStructuralModel(
        id=workflow_id,
        name=name,
        description="",
        nodes=[
            {"node_id": node.id, "position_x": index * 250, "position_y": index * 80}
            for index, node in enumerate(nodes)
        ],
        edges=[
            {
                "id": str(uuid4()),
                "source_node_id": source.id,
                "target_node_id": target.id,
            }
            for source, target in edge_pairs
        ],
    )
    repository = WorkflowStructuralRepository(database)
    repository.create(workflow, nodes)
    return workflow_id, repository


def make_manager(tmp_path, repository):
    store = WorkflowExecutionStore(tmp_path / "executions")
    manager = WorkflowExecutionManager(
        repository,
        ModelProviderRepository(repository.database_path),
        store,
    )
    return manager, store


@pytest.fixture
def local_execution_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_GET(self):
            requests.append({"method": "GET", "path": self.path})
            body = json.dumps(
                {"data": [{"id": 2, "name": "two"}, {"id": 3, "name": "three"}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            request = {"method": "POST", "path": self.path, "body": payload}
            if self.headers.get("X-Template-Test") is not None:
                request["template_header"] = self.headers["X-Template-Test"]
            requests.append(request)
            if self.path.endswith("/messages"):
                response = {
                    "id": "msg-1",
                    "content": [{"type": "text", "text": "Anthropic OK"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 4, "output_tokens": 2},
                }
            elif self.path.endswith("/responses"):
                response = {
                    "id": "resp-1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "reasoning",
                            "content": [
                                {
                                    "type": "reasoning_text",
                                    "text": "private reasoning",
                                }
                            ],
                        },
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "Responses OK"}
                            ],
                        }
                    ],
                    "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                }
            else:
                response = {
                    "id": "chat-1",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "OpenAI OK"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                }
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_script_workflow_persists_context_and_schedules_end_after_upstream_success(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node(
        "START", inputs=[{"name": "question", "type": "string", "value": "hello"}]
    )
    script = make_node(
        "SCRIPT",
        script='result = context["question"].upper()\nprint(result)',
        outputs=[{"name": "answer", "type": "string", "source": "result"}],
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    node_documents = store.get_nodes(workflow_id, started["id"])

    assert finished["status"] == "SUCCESS"
    assert finished["context"]["initial"] == {}
    assert finished["context"]["final"] == {"question": "hello", "answer": "HELLO"}
    by_type = {item["type"]: item for item in node_documents}
    assert set(by_type) == {"START", "SCRIPT", "END"}
    assert {item["status"] for item in node_documents} == {"SUCCESS"}
    assert by_type["SCRIPT"]["inputs"] == {"question": "hello"}
    assert by_type["SCRIPT"]["outputs"] == {"answer": "HELLO"}
    assert by_type["SCRIPT"]["logs"]["attempts"][-1]["console"][0]["content"] == "HELLO\n"
    assert by_type["END"]["inputs"] == {}
    assert by_type["END"]["outputs"] == {}
    assert finished["result"] == {}
    assert next(item for item in finished["nodes"] if item["node_id"] == end.id)["state"] == "FINISHED"


def test_end_ignores_legacy_result_fields_and_only_marks_workflow_success(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START", inputs=[])
    script = make_node(
        "SCRIPT",
        script="answer = {'text': '通过', 'score': 0.95}",
        outputs=[{"name": "agent_answer", "type": "object", "source": "answer"}],
    )
    end = make_node(
        "END",
        outputs=[
            {"name": "text", "type": "string", "source": "agent_answer.text"},
            {"name": "score", "type": "number", "source": "agent_answer.score"},
        ],
    )
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    end_execution = next(
        item for item in store.get_nodes(workflow_id, started["id"]) if item["type"] == "END"
    )

    assert finished["status"] == "SUCCESS"
    assert finished["result"] == {}
    assert finished["context"]["final"] == {
        "agent_answer": {"text": "通过", "score": 0.95}
    }
    assert len(finished["context"]["commits"]) == 1
    assert end_execution["inputs"] == {}
    assert end_execution["outputs"] == {}
    assert "outputs" not in end_execution["structural_snapshot"]


def test_batch_execution_uses_frozen_snapshot_and_case_initial_context(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node(
        "START",
        inputs=[{"name": "input", "type": "object", "value": {"question": "default"}}],
    )
    script = make_node(
        "SCRIPT",
        script='result = context["input"]["question"].upper()',
        outputs=[{"name": "answer", "type": "string", "source": "result"}],
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)
    frozen = workflow_execution_module.snapshot_record(repository.get(workflow_id))
    repository.update(
        repository.get(workflow_id).workflow,
        [
            NODE_STRUCTURAL_ADAPTER.validate_python(
                {
                    **start.model_dump(mode="json"),
                    "inputs": [
                        {"name": "input", "type": "object", "value": {"question": "changed"}}
                    ],
                }
            ),
            script,
            end,
        ],
    )

    started = manager.start_batch(
        frozen,
        {"input": {"question": "batch case"}},
        {
            "type": "BATCH",
            "batch_execution_id": str(uuid4()),
            "case_run_id": str(uuid4()),
            "case_id": "C-1",
            "row_number": 2,
        },
    )
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert finished["status"] == "SUCCESS"
    assert finished["context"]["initial"] == {
        "input": {"question": "batch case"}
    }
    assert finished["context"]["final"] == {
        "input": {"question": "batch case"},
        "answer": "BATCH CASE",
    }
    assert finished["trigger"]["type"] == "BATCH"
    snapshot_start = next(
        item["node"] for item in finished["structural_snapshot"]["nodes"]
        if item["node"]["type"] == "START"
    )
    assert snapshot_start["inputs"][0]["value"] == {"question": "default"}
    start_execution = next(
        item
        for item in store.get_nodes(workflow_id, started["id"])
        if item["type"] == "START"
    )
    assert start_execution["inputs"] == {"input": {"question": "default"}}
    assert start_execution["outputs"] == {}


def test_batch_execution_keeps_unknown_and_retyped_values_out_of_start_snapshot(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node(
        "START", inputs=[{"name": "question", "type": "string", "value": "default"}]
    )
    script = make_node("SCRIPT")
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, _store = make_manager(tmp_path, repository)
    frozen = workflow_execution_module.snapshot_record(repository.get(workflow_id))
    trigger = {
        "type": "BATCH",
        "batch_execution_id": str(uuid4()),
        "case_run_id": str(uuid4()),
        "case_id": "C-1",
        "row_number": 2,
    }

    injected = manager.start_batch(frozen, {"missing": "value"}, trigger)
    injected_finished = wait_for_terminal(_store, workflow_id, injected["id"])
    injected_start = next(
        item["node"] for item in injected_finished["structural_snapshot"]["nodes"]
        if item["node"]["type"] == "START"
    )
    assert injected_finished["context"]["initial"] == {"missing": "value"}
    assert injected_finished["context"]["final"] == {
        "missing": "value",
        "question": "default",
    }
    assert {item["name"]: item["value"] for item in injected_start["inputs"]} == {
        "question": "default"
    }

    retyped = manager.start_batch(frozen, {"question": 123}, trigger)
    retyped_finished = wait_for_terminal(_store, workflow_id, retyped["id"])
    retyped_start = next(
        item["node"] for item in retyped_finished["structural_snapshot"]["nodes"]
        if item["node"]["type"] == "START"
    )
    question = next(item for item in retyped_start["inputs"] if item["name"] == "question")
    assert question == {"name": "question", "type": "string", "value": "default"}
    assert retyped_finished["context"]["initial"] == {"question": 123}
    assert retyped_finished["context"]["final"] == {"question": 123}


def test_missing_script_output_fails_fast_and_never_creates_end_execution(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        script="print('done')",
        outputs=[{"name": "answer", "type": "string", "source": "missing"}],
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    node_documents = store.get_nodes(workflow_id, started["id"])

    assert finished["status"] == "FAILED"
    assert finished["error"]["code"] == "NODE_FAILED"
    assert {item["type"] for item in node_documents} == {"START", "SCRIPT"}
    assert next(item for item in node_documents if item["type"] == "SCRIPT")["error"]["code"] == "SCRIPT_OUTPUT_MISSING"
    end_state = next(item for item in finished["nodes"] if item["node_id"] == end.id)
    assert end_state == {
        "node_id": end.id,
        "node_execution_id": None,
        "state": "NOT_STARTED",
        "reason": "WORKFLOW_FAILED",
    }


def test_script_reports_every_missing_output_name_in_structured_details(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        script="print('done')",
        outputs=[
            {"name": "first", "type": "string", "source": "missing_first"},
            {"name": "second", "type": "string", "source": "missing_second"},
        ],
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    wait_for_terminal(store, workflow_id, started["id"])
    failed = next(
        item
        for item in store.get_nodes(workflow_id, started["id"])
        if item["type"] == "SCRIPT"
    )

    assert failed["error"] == {
        "code": "SCRIPT_OUTPUT_MISSING",
        "message": "Python 顶层变量不存在: missing_first, missing_second",
        "details": {
            "name": "missing_first",
            "names": ["missing_first", "missing_second"],
        },
    }


def test_script_serialization_failure_uses_output_contract_error_without_retry(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        script="result = object()",
        execution={
            "timeout_seconds": 5,
            "max_attempts": 2,
            "retry_interval_seconds": 0,
            "delay_seconds": 0,
        },
        outputs=[{"name": "answer", "type": "object", "source": "result"}],
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    wait_for_terminal(store, workflow_id, started["id"])
    failed = next(
        item
        for item in store.get_nodes(workflow_id, started["id"])
        if item["type"] == "SCRIPT"
    )

    assert failed["error"]["code"] == "SCRIPT_OUTPUT_SERIALIZATION_ERROR"
    assert failed["error"]["details"] == {"name": "result"}
    assert failed["attempt_count"] == 1


@pytest.mark.parametrize(
    ("node_type", "expected_code", "expected_fields"),
    [
        ("SCRIPT", "SCRIPT_CONFIGURATION_INCOMPLETE", ["script"]),
        (
            "LLM",
            "LLM_CONFIGURATION_INCOMPLETE",
            ["model.provider_id", "model.model_name", "context.messages[1].content"],
        ),
        ("HTTP", "HTTP_CONFIGURATION_INCOMPLETE", ["request.url"]),
    ],
)
def test_missing_business_configuration_fails_when_node_is_reached_without_attempt(
    tmp_path, monkeypatch, node_type, expected_code, expected_fields
):
    monkeypatch.setattr(
        workflow_execution_module,
        "stream_tool_worker",
        lambda *_args, **_kwargs: pytest.fail("配置不完整时不应启动真实 Worker"),
    )
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    business = make_node(
        node_type,
        name=f"空白 {node_type}",
        **({"script": ""} if node_type == "SCRIPT" else {}),
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, business, end], [(start, business), (business, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    workflow = wait_for_terminal(store, workflow_id, started["id"])
    documents = store.get_nodes(workflow_id, started["id"])
    failed = next(document for document in documents if document["node_id"] == business.id)

    assert workflow["status"] == "FAILED"
    assert failed["status"] == "FAILED"
    assert failed["started_at"] is None
    assert failed["finished_at"] is not None
    assert failed["duration_ms"] is None
    assert failed["attempt_count"] == 0
    assert [transition["status"] for transition in failed["transitions"]] == [
        "PENDING",
        "FAILED",
    ]
    assert failed["error"]["code"] == expected_code
    assert failed["error"]["details"]["missing_fields"] == expected_fields
    assert failed["error"]["details"]["suggestion"]
    assert f"空白 {node_type}" in failed["error"]["message"]
    assert all(document["type"] != "END" for document in documents)
    end_state = next(item for item in workflow["nodes"] if item["node_id"] == end.id)
    assert end_state == {
        "node_id": end.id,
        "node_execution_id": None,
        "state": "NOT_STARTED",
        "reason": "WORKFLOW_FAILED",
    }


def test_nonempty_missing_llm_reference_fails_at_node_with_friendly_error(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    llm = make_node(
        "LLM",
        name="已删除模型",
        model={"provider_id": "missing-provider", "model_name": "missing-model"},
        context={"messages": [{"role": "SYSTEM", "content": ""}, {"role": "USER", "content": "请回答"}]},
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, llm, end], [(start, llm), (llm, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    wait_for_terminal(store, workflow_id, started["id"])
    failed = next(
        document
        for document in store.get_nodes(workflow_id, started["id"])
        if document["node_id"] == llm.id
    )

    assert failed["status"] == "FAILED"
    assert failed["attempt_count"] == 0
    assert failed["started_at"] is None
    assert failed["error"]["code"] == "LLM_MODEL_NOT_FOUND"
    assert failed["error"]["details"]["missing_fields"] == []
    assert "已删除模型" in failed["error"]["message"]
    assert failed["error"]["details"]["suggestion"]


def test_same_round_ready_scripts_are_observably_running_in_parallel(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    left = make_node(
        "SCRIPT",
        name="left",
        script="import time\ntime.sleep(0.6)\nleft = 'L'",
        outputs=[{"name": "left", "type": "string", "source": "left"}],
    )
    right = make_node(
        "SCRIPT",
        name="right",
        script="import time\ntime.sleep(0.6)\nright = 'R'",
        outputs=[{"name": "right", "type": "string", "source": "right"}],
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database,
        [start, left, right, end],
        [(start, left), (start, right), (left, end), (right, end)],
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    deadline = time.monotonic() + 5
    observed_parallel = False
    while time.monotonic() < deadline:
        current = store.get_workflow(workflow_id, started["id"])
        states = {
            item["node_id"]: item["state"]
            for item in current["nodes"]
        }
        if states[left.id] == states[right.id] == "RUNNING":
            observed_parallel = True
            break
        time.sleep(0.02)
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert observed_parallel
    assert finished["status"] == "SUCCESS"
    assert finished["context"]["final"] == {"left": "L", "right": "R"}


def test_fail_fast_reconciles_every_started_parallel_node(tmp_path):
    database = tmp_path / "fail-fast-reconcile.sqlite3"
    start = make_node("START")
    failing = make_node(
        "SCRIPT",
        name="failing",
        script="finished_without_output = True",
        outputs=[{"name": "required", "type": "string", "source": "required"}],
    )
    delayed = make_node(
        "SCRIPT",
        name="delayed",
        script="value = 'late'",
        execution={
            "timeout_seconds": 5,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 2,
        },
        outputs=[{"name": "late", "type": "string", "source": "value"}],
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database,
        [start, failing, delayed, end],
        [(start, failing), (start, delayed), (failing, end), (delayed, end)],
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    executions = {
        item["node_id"]: item
        for item in store.get_nodes(workflow_id, started["id"])
    }
    entries = {item["node_id"]: item for item in finished["nodes"]}

    assert finished["status"] == "FAILED"
    assert executions[failing.id]["status"] == "FAILED"
    assert executions[delayed.id]["status"] == "INTERRUPTED"
    assert executions[delayed.id]["started_at"] is None
    assert executions[delayed.id]["duration_ms"] is None
    assert entries[failing.id]["state"] == "FINISHED"
    assert entries[delayed.id] == {
        "node_id": delayed.id,
        "node_execution_id": executions[delayed.id]["node_execution_id"],
        "state": "FINISHED",
        "reason": None,
    }
    assert entries[end.id]["state"] == "NOT_STARTED"


def test_scheduler_logic_error_is_not_misreported_as_persistence_failure(
    tmp_path, monkeypatch
):
    database = tmp_path / "scheduler-error.sqlite3"
    start = make_node("START")
    script = make_node("SCRIPT")
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    def fail_scheduler(*_args, **_kwargs):
        raise ValueError("scheduler invariant broke")

    monkeypatch.setattr(manager, "_workflow_node", fail_scheduler)
    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert finished["status"] == "FAILED"
    assert finished["error"]["code"] == "NODE_FAILED"
    assert finished["error"]["details"]["phase"] == "SCHEDULER"
    assert "scheduler invariant broke" in finished["error"]["message"]


def test_script_stays_pending_during_fractional_initial_delay(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        script="result = 'ready'",
        outputs=[{"name": "result", "type": "string", "source": "result"}],
        execution={
            "timeout_seconds": 5,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 0.25,
        },
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    deadline = time.monotonic() + 3
    pending_document = None
    while time.monotonic() < deadline:
        node_documents = store.get_nodes(workflow_id, started["id"])
        pending_document = next(
            (item for item in node_documents if item["type"] == "SCRIPT"), None
        )
        if pending_document is not None:
            break
        time.sleep(0.01)

    assert pending_document is not None
    assert pending_document["status"] == "PENDING"
    assert pending_document["attempt_count"] == 0
    assert pending_document["started_at"] is None
    workflow_pending = store.get_workflow(workflow_id, started["id"])
    script_entry = next(
        item for item in workflow_pending["nodes"] if item["node_id"] == script.id
    )
    assert script_entry["state"] == "RUNNING"

    finished = wait_for_terminal(store, workflow_id, started["id"])
    final_script = next(
        item
        for item in store.get_nodes(workflow_id, started["id"])
        if item["type"] == "SCRIPT"
    )
    assert finished["status"] == "SUCCESS"
    assert final_script["duration_ms"] is not None


def test_business_node_duration_starts_after_initial_delay(monkeypatch):
    class MemoryStore:
        def write_node(self, _document):
            return None

    class Controller:
        def interrupted(self):
            return False

    clock = [10.0]
    monkeypatch.setattr(workflow_node_runner_base_module.time, "monotonic", lambda: clock[0])

    def finish_delay(_controller, _delay_milliseconds):
        clock[0] += 5.0
        return False

    monkeypatch.setattr(
        workflow_node_runner_base_module.NodeRunnerBase,
        "_wait_interruptibly",
        staticmethod(finish_delay),
    )
    runner = workflow_node_runner_base_module.NodeRunnerBase(None, MemoryStore(), None)
    node = make_node(
        "SCRIPT",
        execution={
            "timeout_seconds": 5,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 5,
        },
    )
    document = runner._base_node(
        {"id": str(uuid4()), "workflow_id": str(uuid4())},
        node,
        str(uuid4()),
    )

    started_clock = runner._begin_business_node(document, node, Controller())
    clock[0] += 0.25
    runner._finish_node(document, "SUCCESS", started_clock)

    assert document["status"] == "SUCCESS"
    assert document["duration_ms"] == 250


def test_initial_delay_and_retry_interval_are_applied_once_and_timeout_is_converted(
    tmp_path, monkeypatch
):
    waits = []
    worker_timeouts = []
    results = [
        {"ok": False, "error": "temporary failure"},
        {"ok": True, "python_variables": {"result": "ok"}},
    ]

    def record_wait(_controller, delay_milliseconds):
        waits.append(delay_milliseconds)
        return False

    def fake_worker(_payload, _on_log, _run_id, *, timeout_seconds, **_kwargs):
        worker_timeouts.append(timeout_seconds)
        return results.pop(0)

    monkeypatch.setattr(
        workflow_node_runner_base_module.NodeRunnerBase,
        "_wait_interruptibly",
        staticmethod(record_wait),
    )
    monkeypatch.setattr(workflow_execution_module, "stream_tool_worker", fake_worker)
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        outputs=[{"name": "result", "type": "string", "source": "result"}],
        execution={
            "timeout_seconds": 0.125,
            "max_attempts": 1,
            "retry_interval_seconds": 0.2,
            "delay_seconds": 0.15,
        },
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert finished["status"] == "SUCCESS"
    assert waits == [150, 200]
    assert worker_timeouts == [0.125, 0.125]


def test_global_cancel_interrupts_running_script_and_end_is_not_started(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        script="import time\ntime.sleep(30)\nresult = 'late'",
        outputs=[{"name": "result", "type": "string", "source": "result"}],
        execution={
            "timeout_seconds": 60,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 0,
        },
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)
    started = manager.start(workflow_id)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = store.get_workflow(workflow_id, started["id"])
        script_entry = next(item for item in current["nodes"] if item["node_id"] == script.id)
        if script_entry["state"] == "RUNNING":
            break
        time.sleep(0.02)

    assert manager.cancel(started["id"])
    finished = wait_for_terminal(store, workflow_id, started["id"])
    node_documents = store.get_nodes(workflow_id, started["id"])

    assert finished["status"] == "INTERRUPTED"
    assert finished["error"]["code"] == "USER_INTERRUPTED"
    assert next(item for item in node_documents if item["type"] == "SCRIPT")["status"] == "INTERRUPTED"
    assert all(item["type"] != "END" for item in node_documents)


def test_workflow_manager_shutdown_interrupts_active_execution(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        script="import time\ntime.sleep(30)\nresult = 'late'",
        outputs=[{"name": "result", "type": "string", "source": "result"}],
        execution={
            "timeout_seconds": 60,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 0,
        },
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database,
        [start, script, end],
        [(start, script), (script, end)],
    )
    manager, store = make_manager(tmp_path, repository)
    started = manager.start(workflow_id)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = store.get_workflow(workflow_id, started["id"])
        script_entry = next(
            item for item in current["nodes"] if item["node_id"] == script.id
        )
        if script_entry["state"] == "RUNNING":
            break
        time.sleep(0.02)
    manager.shutdown(wait_seconds=8)
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert finished["status"] == "INTERRUPTED"
    assert not manager.is_active(started["id"])


def test_node_test_manager_shutdown_interrupts_active_test(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    manager = NodeTestManager(
        ModelProviderRepository(database),
    )
    node = make_node(
        "SCRIPT",
        script="import time\ntime.sleep(30)\nresult = 'late'",
        execution={
            "timeout_seconds": 60,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 0,
        },
    )
    _envelope, created = manager.start(str(uuid4()), node, {})

    assert created
    manager.shutdown(wait_seconds=8)
    assert manager._threads == {}
    assert manager._active_by_node == {}


def test_node_test_start_and_shutdown_do_not_expose_unstarted_thread(
    tmp_path, monkeypatch
):
    database = tmp_path / "workflow.sqlite3"
    manager = NodeTestManager(
        ModelProviderRepository(database),
    )
    node = make_node("SCRIPT", script="result = 'done'")
    entered_start = threading.Event()
    release_start = threading.Event()
    original_start = threading.Thread.start

    def delayed_start(thread):
        if thread.name.startswith("node-test-"):
            entered_start.set()
            assert release_start.wait(timeout=2)
        return original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", delayed_start)
    with ThreadPoolExecutor(max_workers=2) as pool:
        start_future = pool.submit(manager.start, str(uuid4()), node, {})
        assert entered_start.wait(timeout=2)
        shutdown_future = pool.submit(manager.shutdown, wait_seconds=2)
        time.sleep(0.05)
        assert not shutdown_future.done()
        release_start.set()
        _envelope, created = start_future.result(timeout=3)
        shutdown_future.result(timeout=3)

    assert created
    assert manager._threads == {}


def test_global_cancel_interrupts_initial_delay_before_first_attempt(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node(
        "SCRIPT",
        script="result = 'late'",
        outputs=[{"name": "result", "type": "string", "source": "result"}],
        execution={
            "timeout_seconds": 5,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 30,
        },
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)
    started = manager.start(workflow_id)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        script_execution = next(
            (
                item
                for item in store.get_nodes(workflow_id, started["id"])
                if item["type"] == "SCRIPT"
            ),
            None,
        )
        if script_execution is not None and script_execution["status"] == "PENDING":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("SCRIPT 未进入首次延迟 PENDING")

    assert manager.cancel(started["id"])
    finished = wait_for_terminal(store, workflow_id, started["id"])
    script_execution = next(
        item
        for item in store.get_nodes(workflow_id, started["id"])
        if item["type"] == "SCRIPT"
    )

    assert finished["status"] == "INTERRUPTED"
    assert script_execution["status"] == "INTERRUPTED"
    assert script_execution["started_at"] is None
    assert script_execution["duration_ms"] is None
    assert script_execution["attempt_count"] == 0
    assert script_execution["logs"]["attempts"] == []


def test_store_recovers_incomplete_workflow_and_node_after_restart(tmp_path):
    store = WorkflowExecutionStore(tmp_path / "executions")
    workflow_id = str(uuid4())
    execution_id = str(uuid4())
    node_execution_id = str(uuid4())
    workflow = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "status": "RUNNING",
        "created_at": "2026-07-26T00:00:00.000Z",
        "finished_at": None,
        "error": None,
    }
    store.create(workflow)
    store.write_node(
        {
            "workflow_execution_id": execution_id,
            "workflow_id": workflow_id,
            "node_execution_id": node_execution_id,
            "status": "RUNNING",
            "finished_at": None,
            "transitions": [],
            "error": None,
        }
    )

    assert store.recover_incomplete() == 1
    recovered = store.get_workflow(workflow_id, execution_id)
    recovered_node = store.get_nodes(workflow_id, execution_id)[0]
    assert recovered["status"] == "FAILED"
    assert recovered["error"]["code"] == "PROCESS_RESTARTED"
    assert recovered_node["status"] == "FAILED"
    assert recovered_node["error"]["code"] == "RUNTIME_LOST"


def test_store_read_retries_transient_windows_permission_error(tmp_path, monkeypatch):
    store = WorkflowExecutionStore(tmp_path / "executions")
    workflow_id = str(uuid4())
    execution_id = str(uuid4())
    document = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "status": "SUCCESS",
    }
    store.create(document)
    original_read_text = Path.read_text
    attempts = 0

    def transient_read_error(path, *args, **kwargs):
        nonlocal attempts
        if path.name == "workflow.json" and attempts < 2:
            attempts += 1
            raise PermissionError("atomic replace is temporarily holding the file")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient_read_error)

    assert store.get_workflow(workflow_id, execution_id) == document
    assert attempts == 2


def test_store_atomic_write_retries_transient_windows_permission_error(tmp_path, monkeypatch):
    store = WorkflowExecutionStore(tmp_path / "executions")
    workflow_id = str(uuid4())
    execution_id = str(uuid4())
    document = {"id": execution_id, "workflow_id": workflow_id, "status": "SUCCESS"}
    original_replace = workflow_execution_store_module.os.replace
    attempts = 0

    def transient_replace_error(source, target):
        nonlocal attempts
        if Path(target).name == "workflow.json" and attempts < 2:
            attempts += 1
            raise PermissionError("workflow.json is temporarily locked")
        return original_replace(source, target)

    monkeypatch.setattr(
        workflow_execution_store_module.os,
        "replace",
        transient_replace_error,
    )

    store.create(document)

    assert store.get_workflow(workflow_id, execution_id) == document
    assert attempts == 2
    assert list(store.execution_root(workflow_id, execution_id).glob("*.tmp")) == []


def test_store_archives_expired_terminal_executions_with_transparent_node_reads(
    tmp_path, monkeypatch
):
    store = WorkflowExecutionStore(tmp_path / "executions")
    workflow_id = str(uuid4())
    batch_id = str(uuid4())
    expired_id = str(uuid4())
    recent_id = str(uuid4())
    running_id = str(uuid4())
    expired = {
        "id": expired_id,
        "workflow_id": workflow_id,
        "trigger": {"type": "BATCH", "batch_execution_id": batch_id},
        "status": "SUCCESS",
        "created_at": "2026-07-20T12:00:00.000Z",
        "finished_at": "2026-07-20T12:01:00.000Z",
    }
    node = {
        "node_execution_id": str(uuid4()),
        "workflow_id": workflow_id,
        "workflow_execution_id": expired_id,
        "type": "SCRIPT",
        "status": "SUCCESS",
        "started_at": "2026-07-20 20:00:00",
        "logs": ["complete"],
    }
    recent = {
        **expired,
        "id": recent_id,
        "trigger": {"type": "MANUAL"},
        "created_at": "2026-07-30T12:00:00.000Z",
        "finished_at": "2026-07-30T12:01:00.000Z",
    }
    running = {**expired, "id": running_id, "status": "RUNNING"}
    store.create(expired)
    store.write_node(node)
    store.create(recent)
    store.create(running)

    archived = store.archive_expired(
        now=datetime(2026, 7, 31, 12, tzinfo=timezone.utc)
    )

    assert archived == 1
    assert not store.execution_root(workflow_id, expired_id).exists()
    original_read = store._read
    manifest_reads = 0

    def counted_read(path):
        nonlocal manifest_reads
        if path.name.startswith("manifest-"):
            manifest_reads += 1
        return original_read(path)

    monkeypatch.setattr(store, "_read", counted_read)
    assert store.get_workflow(workflow_id, expired_id) == expired
    assert store.get_nodes(workflow_id, expired_id) == [node]
    assert store.get_workflow(workflow_id, recent_id) == recent
    assert store.get_workflow(workflow_id, running_id) == running
    assert {item["id"] for item in store.list(workflow_id)} == {
        expired_id,
        recent_id,
        running_id,
    }
    assert next(item for item in store.list(workflow_id) if item["id"] == expired_id) == expired
    assert manifest_reads == 1
    manifests = list(store.archive_root.glob(f"{workflow_id}/**/manifest-*.json"))
    assert len(manifests) == 1
    manifest = WorkflowExecutionStore._read(manifests[0])
    assert manifest["version"] == 2
    assert manifest["batch_execution_id"] == batch_id
    assert manifest["executions"][0]["id"] == expired_id
    assert "workflow" not in manifest["executions"][0]
    assert manifest["executions"][0]["created_at"] == expired["created_at"]

    store.create(expired)
    store.write_node(node)
    temporary = store.root / ".interrupted-write.tmp"
    temporary.write_text("partial", encoding="utf-8")
    staged_deletion = store.root / f".deleting-{workflow_id}-{uuid4()}"
    staged_deletion.mkdir()
    (staged_deletion / "marker.json").write_text("{}", encoding="utf-8")
    orphan = manifests[0].parent / "executions-orphan.zip"
    with zipfile.ZipFile(orphan, "w") as archive:
        archive.writestr(f"{expired_id}/workflow.json", json.dumps(expired))

    recovered = store.recover_interrupted_archives()

    assert recovered == {
        "temporary_files": 2,
        "orphan_archives": 1,
        "hot_duplicates": 1,
    }
    assert not store.execution_root(workflow_id, expired_id).exists()
    assert not orphan.exists()
    assert not temporary.exists()
    assert not staged_deletion.exists()

    store.delete_workflow_root(workflow_id)
    assert not (store.archive_root / workflow_id).exists()


def test_store_reads_legacy_full_workflow_archive_manifest(tmp_path):
    store = WorkflowExecutionStore(tmp_path / "executions")
    workflow_id = str(uuid4())
    execution_id = str(uuid4())
    document = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "trigger": {"type": "MANUAL"},
        "status": "SUCCESS",
        "created_at": "2026-07-20T12:00:00.000Z",
        "finished_at": "2026-07-20T12:01:00.000Z",
        "context": {"commits": [], "final": {"answer": 42}},
    }
    target = store.archive_root / workflow_id / "date=2026-07-20" / "batch=manual"
    target.mkdir(parents=True)
    archive_name = "executions-legacy.zip"
    with zipfile.ZipFile(target / archive_name, "w") as archive:
        archive.writestr(
            f"{execution_id}/workflow.json",
            json.dumps(document, ensure_ascii=False),
        )
    WorkflowExecutionStore._atomic_write(
        target / "manifest-legacy.json",
        {
            "version": 1,
            "archive": archive_name,
            "workflow_id": workflow_id,
            "date": "2026-07-20",
            "batch_execution_id": None,
            "created_at": "2026-07-20T12:02:00.000Z",
            "executions": [{"id": execution_id, "workflow": document}],
        },
    )

    assert store.get_workflow(workflow_id, execution_id) == document
    assert store.list(workflow_id) == [document]


def test_store_archives_oldest_terminal_executions_with_hot_window_and_limit(tmp_path):
    store = WorkflowExecutionStore(tmp_path / "executions")
    workflow_id = str(uuid4())
    oldest_id = str(uuid4())
    older_id = str(uuid4())
    recent_id = str(uuid4())
    running_id = str(uuid4())

    def document(execution_id, status, created_at, finished_at):
        return {
            "id": execution_id,
            "workflow_id": workflow_id,
            "trigger": {"type": "MANUAL"},
            "status": status,
            "created_at": created_at,
            "finished_at": finished_at,
        }

    oldest = document(
        oldest_id,
        "SUCCESS",
        "2026-07-31T10:00:00.000Z",
        "2026-07-31T10:01:00.000Z",
    )
    older = document(
        older_id,
        "FAILED",
        "2026-07-31T10:10:00.000Z",
        "2026-07-31T10:11:00.000Z",
    )
    recent = document(
        recent_id,
        "SUCCESS",
        "2026-07-31T11:50:00.000Z",
        "2026-07-31T11:55:00.000Z",
    )
    running = document(
        running_id,
        "RUNNING",
        "2026-07-31T10:20:00.000Z",
        None,
    )
    for item in (oldest, older, recent, running):
        store.create(item)

    archived = store.archive_expired(
        retention_days=None,
        retention_seconds=15 * 60,
        max_executions=1,
        now=datetime(2026, 7, 31, 12, tzinfo=timezone.utc),
    )

    assert archived == 1
    assert not store.execution_root(workflow_id, oldest_id).exists()
    assert store.execution_root(workflow_id, older_id).exists()
    assert store.execution_root(workflow_id, recent_id).exists()
    assert store.execution_root(workflow_id, running_id).exists()

    assert store.archive_expired(
        retention_days=None,
        retention_seconds=15 * 60,
        max_executions=1,
        now=datetime(2026, 7, 31, 12, tzinfo=timezone.utc),
    ) == 1
    assert not store.execution_root(workflow_id, older_id).exists()
    assert store.execution_root(workflow_id, recent_id).exists()
    assert store.execution_root(workflow_id, running_id).exists()


def test_retention_scheduler_archives_on_start_and_stops_cleanly(tmp_path, monkeypatch):
    store = WorkflowExecutionStore(tmp_path / "executions")
    calls = []

    def archive_expired(*, retention_days, retention_seconds, max_executions):
        calls.append((retention_days, retention_seconds, max_executions))
        return 3

    monkeypatch.setattr(store, "archive_expired", archive_expired)
    scheduler = workflow_execution_store_module.WorkflowExecutionRetentionScheduler(
        store,
        retention_seconds=15 * 60,
        interval_seconds=60,
        max_executions_per_pass=100,
    )

    assert scheduler.start() == 3
    assert scheduler.last_recovery == {
        "temporary_files": 0,
        "orphan_archives": 0,
        "hot_duplicates": 0,
    }
    scheduler.shutdown()
    assert calls == [(None, 15 * 60, 100)]


def test_execution_json_is_readable_standard_json_without_execution_database_tables(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    script = make_node("SCRIPT", script="result = {'id': 3}", outputs=[])
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, script, end], [(start, script), (script, end)]
    )
    manager, store = make_manager(tmp_path, repository)
    started = manager.start(workflow_id)
    wait_for_terminal(store, workflow_id, started["id"])

    workflow_path = store.execution_root(workflow_id, started["id"]) / "workflow.json"
    parsed = json.loads(workflow_path.read_text(encoding="utf-8"))
    assert parsed["structural_snapshot"]["workflow"]["id"] == workflow_id
    assert "\n  " not in workflow_path.read_text(encoding="utf-8")
    assert list(workflow_path.parent.glob("*.tmp")) == []


def test_http_node_sends_real_request_and_extracts_filtered_response(tmp_path, local_execution_server):
    base_url, requests = local_execution_server
    database = tmp_path / "workflow.sqlite3"
    start = make_node(
        "START", inputs=[{"name": "lookup_id", "type": "integer", "value": 3}]
    )
    http_node = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "HTTP",
            "name": "本机查询",
            "description": "",
            "request": {
                "method": "GET",
                "url": base_url + "/items",
                "follow_redirects": True,
                "headers": [],
                "params": [{"key": "wanted", "value": "${lookup_id}"}],
                "body": {"type": "none", "content": None},
            },
            "network": {
                "proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None},
                "verify_ssl": True,
            },
            "response": {"mode": "AUTO", "success_statuses": ["200-299"]},
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": 0,
                "retry_interval_seconds": 0,
                "delay_seconds": 0,
                "retry_non_idempotent": False,
                "retry_statuses": [500, 502, 503, 504],
            },
            "outputs": [
                {
                    "name": "selected_name",
                    "type": "string",
                    "source": "response.body.data[id==3].name",
                }
            ],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database,
        [start, http_node, end],
        [(start, http_node), (http_node, end)],
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    http_execution = next(
        item for item in store.get_nodes(workflow_id, started["id"]) if item["type"] == "HTTP"
    )

    assert finished["status"] == "SUCCESS"
    assert finished["context"]["final"] == {"lookup_id": 3, "selected_name": "three"}
    assert http_execution["inputs"] == {"lookup_id": 3}
    assert http_execution["response"]["body"]["data"][1] == {"id": 3, "name": "three"}
    assert requests == [{"method": "GET", "path": "/items?wanted=3"}]


def test_batch_external_template_variable_runs_from_initial_context_without_start_declaration(
    tmp_path, local_execution_server
):
    base_url, requests = local_execution_server
    database = tmp_path / "workflow.sqlite3"
    start = make_node(
        "START",
        inputs=[{"name": "start_default", "type": "string", "value": "kept"}],
    )
    http_node = make_node(
        "HTTP",
        request={
            "method": "GET",
            "url": base_url + "/items",
            "params": [{"key": "wanted", "value": "${lookup_id}"}],
        },
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database,
        [start, http_node, end],
        [(start, http_node), (http_node, end)],
    )
    manager, store = make_manager(tmp_path, repository)
    frozen = workflow_execution_module.snapshot_record(repository.get(workflow_id))

    started = manager.start_batch(
        frozen,
        {"lookup_id": 3},
        {
            "type": "BATCH",
            "batch_execution_id": str(uuid4()),
            "case_run_id": str(uuid4()),
            "case_id": "external-1",
            "row_number": 1,
        },
    )
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert finished["status"] == "SUCCESS"
    assert finished["context"]["initial"] == {"lookup_id": 3}
    assert finished["context"]["final"] == {
        "lookup_id": 3,
        "start_default": "kept",
    }
    snapshot_start = next(
        item["node"]
        for item in finished["structural_snapshot"]["nodes"]
        if item["node"]["type"] == "START"
    )
    assert snapshot_start["inputs"] == [
        {"name": "start_default", "type": "string", "value": "kept"}
    ]
    assert requests == [{"method": "GET", "path": "/items?wanted=3"}]


def test_http_raw_json_template_safely_resolves_all_request_fields(
    tmp_path, local_execution_server
):
    base_url, requests = local_execution_server
    question = '中文 "quote" \\ path\nnext line'
    database = tmp_path / "workflow.sqlite3"
    start = make_node(
        "START",
        inputs=[
            {
                "name": "input",
                "type": "object",
                "value": {
                    "question": question,
                    "path": "template",
                    "query": "a b",
                    "header": "template-header",
                },
            }
        ],
    )
    http_node = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "HTTP",
            "name": "HTTP JSON 模板",
            "description": "",
            "request": {
                "method": "POST",
                "url": base_url + "/${input.path}",
                "follow_redirects": True,
                "headers": [{"key": "X-Template-Test", "value": "${input.header}"}],
                "params": [{"key": "q", "value": "${input.query}"}],
                "body": {
                    "type": "raw",
                    "content": None,
                    "template_text": '{"question": ${input.question}}',
                },
            },
            "network": {
                "proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None},
                "verify_ssl": True,
            },
            "response": {"mode": "AUTO", "success_statuses": ["200-299"]},
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": 0,
                "retry_interval_seconds": 0,
                "delay_seconds": 0,
                "retry_non_idempotent": False,
                "retry_statuses": [500],
            },
            "outputs": [],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, http_node, end], [(start, http_node), (http_node, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    http_execution = next(
        item for item in store.get_nodes(workflow_id, started["id"]) if item["type"] == "HTTP"
    )

    assert finished["status"] == "SUCCESS"
    assert http_execution["inputs"] == {
        "input": {
            "question": question,
            "path": "template",
            "query": "a b",
            "header": "template-header",
        }
    }
    assert requests == [
        {
            "method": "POST",
            "path": "/template?q=a+b",
            "body": {"question": question},
            "template_header": "template-header",
        }
    ]


@pytest.mark.parametrize(
    ("status_code", "expected_attempts"),
    [(418, 1), (500, 3), ("parse-error", 1)],
)
def test_http_retry_statuses_control_retries_and_request_options_reach_worker(
    tmp_path, monkeypatch, status_code, expected_attempts
):
    payloads = []

    def fake_worker(payload, _on_log, _run_id, **_kwargs):
        payloads.append(payload)
        if status_code == "parse-error":
            return {
                "ok": False,
                "error": "响应 Body 不是合法 JSON",
                "error_code": "HTTP_RESPONSE_PARSE_ERROR",
            }
        facts = {
            "request": {"method": "GET", "url": payload["request"]["url"], "headers": [], "body_type": "none", "body": None},
            "redirects": [],
            "response": {"status_code": status_code, "headers": [], "body_type": "TEXT", "body": "failed"},
        }
        return {"ok": True, "response": facts}

    monkeypatch.setattr(workflow_execution_module, "stream_tool_worker", fake_worker)
    database = tmp_path / "workflow.sqlite3"
    start = make_node("START")
    http_node = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "HTTP",
            "name": "Request Options",
            "description": "",
            "request": {"method": "GET", "url": "https://example.test", "follow_redirects": False, "headers": [], "params": [], "body": {"type": "none", "content": None}},
            "network": {"proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None}, "verify_ssl": False},
            "response": {"mode": "TEXT", "success_statuses": [200]},
            "execution": {"timeout_seconds": 5, "max_attempts": 2, "retry_interval_seconds": 0, "delay_seconds": 0, "retry_non_idempotent": False, "retry_statuses": [500]},
            "outputs": [],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(database, [start, http_node, end], [(start, http_node), (http_node, end)])
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert finished["status"] == "FAILED"
    assert len(payloads) == expected_attempts
    assert payloads[0]["request"]["follow_redirects"] is False
    assert payloads[0]["request"]["response_mode"] == "TEXT"
    assert payloads[0]["network"] == {
        "proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None},
        "verify_ssl": False,
    }


@pytest.mark.parametrize(
    ("source", "output_type", "expected_error"),
    [
        (
            "response.body.data[-3].name",
            "string",
            "HTTP_OUTPUT_SOURCE_EVALUATION_ERROR",
        ),
        (
            "response.body.data[-1]",
            "integer",
            "HTTP_OUTPUT_TYPE_MISMATCH",
        ),
    ],
)
def test_http_node_classifies_output_source_and_type_errors(
    tmp_path,
    local_execution_server,
    source,
    output_type,
    expected_error,
):
    base_url, requests = local_execution_server
    database = tmp_path / f"{expected_error}.sqlite3"
    start = make_node("START")
    http_node = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "HTTP",
            "name": "HTTP 输出错误分类",
            "description": "",
            "request": {
                "method": "GET",
                "url": base_url + "/items",
                "follow_redirects": True,
                "headers": [],
                "params": [],
                "body": {"type": "none", "content": None},
            },
            "network": {
                "proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None},
                "verify_ssl": True,
            },
            "response": {"mode": "AUTO", "success_statuses": ["200-299"]},
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": 0,
                "retry_interval_seconds": 0,
                "delay_seconds": 0,
                "retry_non_idempotent": False,
                "retry_statuses": [500, 502, 503, 504],
            },
            "outputs": [{"name": "answer", "type": output_type, "source": source}],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, http_node, end], [(start, http_node), (http_node, end)]
    )
    manager, store = make_manager(tmp_path, repository)

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    http_execution = next(
        item for item in store.get_nodes(workflow_id, started["id"])
        if item["type"] == "HTTP"
    )

    assert finished["status"] == "FAILED"
    assert http_execution["status"] == "FAILED"
    assert http_execution["error"]["code"] == expected_error
    assert http_execution["outputs"] == {}
    assert http_execution["response"]["body"]["data"][-1] == {"id": 3, "name": "three"}
    assert http_execution["attempt_count"] == 1
    assert http_execution["attempts"][-1]["status"] == "SUCCESS"
    assert http_execution["attempts"][-1]["error"] is None
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("protocol", "model_name", "source", "expected", "path_suffix"),
    [
        (
            "OPENAI_COMPATIBLE",
            "local-openai",
            "result.output",
            "OpenAI OK",
            "/chat/completions",
        ),
        (
            "OPENAI_RESPONSES",
            "local-responses",
            "result.output",
            "Responses OK",
            "/responses",
        ),
        (
            "ANTHROPIC",
            "local-anthropic",
            "result.output",
            "Anthropic OK",
            "/messages",
        ),
    ],
)
def test_llm_node_uses_real_openai_and_anthropic_protocols(
    tmp_path,
    local_execution_server,
    protocol,
    model_name,
    source,
    expected,
    path_suffix,
):
    base_url, requests = local_execution_server
    database = tmp_path / f"{protocol}.sqlite3"
    model_repository = ModelProviderRepository(database)
    provider = model_repository.create(
        ModelProviderRecord(
            name=protocol,
            api_key="test-key",
            base_url=base_url + "/v1",
            protocol=protocol,
            proxy_mode="DIRECT",
            verify_ssl=True,
            models=[model_name],
            model_configs={model_name: {"default_body": {"temperature": 0}}},
        )
    )
    start = make_node(
        "START", inputs=[{"name": "question", "type": "string", "value": "真实请求"}]
    )
    llm = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "LLM",
            "name": protocol,
            "description": "",
            "model": {"provider_id": provider.id, "model_name": model_name},
            "context": {
                "messages": [
                    {"role": "SYSTEM", "content": "系统"},
                    {"role": "USER", "content": "示例问题"},
                    {"role": "ASSISTANT", "content": "示例回答"},
                    {"role": "USER", "content": "问题：${question}"},
                ]
            },
            "generation": {
                "parameters": {
                    (
                        "max_output_tokens"
                        if protocol == "OPENAI_RESPONSES"
                        else "max_tokens"
                    ): 64
                }
            },
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": 0,
                "retry_interval_seconds": 0,
                "delay_seconds": 0,
            },
            "outputs": [{"name": "model_text", "type": "string", "source": source}],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, llm, end], [(start, llm), (llm, end)]
    )
    manager = WorkflowExecutionManager(
        repository, model_repository, WorkflowExecutionStore(tmp_path / f"runs-{protocol}")
    )
    store = manager.store

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])
    llm_execution = next(
        item for item in store.get_nodes(workflow_id, started["id"]) if item["type"] == "LLM"
    )

    assert finished["status"] == "SUCCESS"
    assert finished["context"]["final"]["model_text"] == expected
    assert llm_execution["response_received"] is True
    assert llm_execution["request"]["stream"] is False
    assert llm_execution["request"]["temperature"] == 0
    token_field = (
        "max_output_tokens" if protocol == "OPENAI_RESPONSES" else "max_tokens"
    )
    assert llm_execution["request"][token_field] == 64
    assert requests[0]["path"].endswith(path_suffix)
    assert requests[0]["body"]["model"] == model_name
    if protocol == "ANTHROPIC":
        assert requests[0]["body"]["system"] == "系统"
        assert requests[0]["body"]["messages"] == [
            {"role": "user", "content": "示例问题"},
            {"role": "assistant", "content": "示例回答"},
            {"role": "user", "content": "问题：真实请求"},
        ]
    elif protocol == "OPENAI_RESPONSES":
        assert "messages" not in requests[0]["body"]
        assert requests[0]["body"]["input"] == [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "示例问题"},
            {"role": "assistant", "content": "示例回答"},
            {"role": "user", "content": "问题：真实请求"},
        ]
        assert llm_execution["usage"] == {
            "input_tokens": 5,
            "output_tokens": 3,
            "total_tokens": 8,
        }
        assert llm_execution["response"]["output"][0]["type"] == "reasoning"
        assert llm_execution["outputs"] == {"model_text": "Responses OK"}
    else:
        assert requests[0]["body"]["messages"] == [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "示例问题"},
            {"role": "assistant", "content": "示例回答"},
            {"role": "user", "content": "问题：真实请求"},
        ]


def test_llm_node_rejects_cross_protocol_parameters_before_request(
    tmp_path, local_execution_server
):
    base_url, requests = local_execution_server
    database = tmp_path / "cross-protocol.sqlite3"
    model_repository = ModelProviderRepository(database)
    provider = model_repository.create(
        ModelProviderRecord(
            name="Claude",
            api_key="test-key",
            base_url=base_url + "/v1/chat/completions",
            protocol="ANTHROPIC",
            proxy_mode="DIRECT",
            models=["claude-test"],
        )
    )
    start = make_node("START")
    llm = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "LLM",
            "name": "Claude 参数校验",
            "description": "",
            "model": {"provider_id": provider.id, "model_name": "claude-test"},
            "context": {
                "messages": [
                    {"role": "SYSTEM", "content": ""},
                    {"role": "USER", "content": "hello"},
                ]
            },
            "generation": {
                "parameters": {"response_format": {"type": "json_object"}}
            },
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": 0,
                "retry_interval_seconds": 0,
                "delay_seconds": 0,
            },
            "outputs": [{"name": "text", "type": "string", "source": "result.output"}],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, llm, end], [(start, llm), (llm, end)]
    )
    manager = WorkflowExecutionManager(
        repository, model_repository, WorkflowExecutionStore(tmp_path / "cross-runs")
    )

    started = manager.start(workflow_id)
    finished = wait_for_terminal(manager.store, workflow_id, started["id"])
    llm_execution = next(
        item
        for item in manager.store.get_nodes(workflow_id, started["id"])
        if item["type"] == "LLM"
    )

    assert finished["status"] == "FAILED"
    assert requests == []
    assert llm_execution["error"]["code"] == "LLM_EXECUTION_ERROR"
    assert "response_format" in llm_execution["error"]["message"]


def _llm_retry_fixture(tmp_path, *, max_attempts=1):
    database = tmp_path / f"llm-retry-{uuid4()}.sqlite3"
    model_repository = ModelProviderRepository(database)
    provider = model_repository.create(
        ModelProviderRecord(
            name="LLM retry fixture",
            api_key="test-key",
            base_url="https://example.invalid/v1",
            protocol="OPENAI_COMPATIBLE",
            proxy_mode="DIRECT",
            verify_ssl=True,
            models=["fixture-model"],
        )
    )
    start = make_node("START")
    llm = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "LLM",
            "name": "LLM retry fixture",
            "description": "",
            "model": {"provider_id": provider.id, "model_name": "fixture-model"},
            "context": {
                "messages": [
                    {"role": "SYSTEM", "content": ""},
                    {"role": "USER", "content": "hello"},
                ]
            },
            "generation": {"parameters": {}},
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": max_attempts,
                "retry_interval_seconds": 0,
                "delay_seconds": 0,
            },
            "outputs": [
                {"name": "answer", "type": "string", "source": "result.output"}
            ],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, llm, end], [(start, llm), (llm, end)]
    )
    manager = WorkflowExecutionManager(
        repository,
        model_repository,
        WorkflowExecutionStore(tmp_path / f"llm-runs-{uuid4()}"),
    )
    return workflow_id, manager


def test_llm_response_parse_error_retries_and_preserves_attempt_facts(tmp_path):
    workflow_id, manager = _llm_retry_fixture(tmp_path)
    responses = iter(
        [
            {"unexpected": True},
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "recovered"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ]
    )
    manager.node_executor.runners["LLM"].stream_worker = lambda *_args, **_kwargs: {
        "ok": True,
        "response": {"response": {"status_code": 200, "body": next(responses)}},
    }

    started = manager.start(workflow_id)
    finished = wait_for_terminal(manager.store, workflow_id, started["id"])
    execution = next(
        item
        for item in manager.store.get_nodes(workflow_id, started["id"])
        if item["type"] == "LLM"
    )

    assert finished["status"] == "SUCCESS"
    assert execution["attempt_count"] == 2
    assert [item["status"] for item in execution["attempts"]] == ["FAILED", "SUCCESS"]
    assert execution["attempts"][0]["error"]["code"] == "LLM_RESPONSE_PARSE_ERROR"
    assert execution["outputs"] == {"answer": "recovered"}


def test_llm_usage_records_invalid_values_and_derives_valid_total(tmp_path):
    workflow_id, manager = _llm_retry_fixture(tmp_path, max_attempts=0)
    response = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 3,
            "total_tokens": "5",
        },
    }
    manager.node_executor.runners["LLM"].stream_worker = lambda *_args, **_kwargs: {
        "ok": True,
        "response": {"response": {"status_code": 200, "body": response}},
    }

    started = manager.start(workflow_id)
    wait_for_terminal(manager.store, workflow_id, started["id"])
    execution = next(
        item
        for item in manager.store.get_nodes(workflow_id, started["id"])
        if item["type"] == "LLM"
    )

    assert execution["usage"] == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }
    assert execution["usage_errors"] == [
        {
            "attempt": 1,
            "field": "total_tokens",
            "code": "LLM_USAGE_VALUE_INVALID",
            "value": "5",
            "message": "必须是大于等于 0 的整数",
        }
    ]


def test_llm_attempt_payload_budget_omits_whole_response_only(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        workflow_llm_runner_module, "LLM_ATTEMPT_PAYLOAD_BUDGET_BYTES", 512
    )
    workflow_id, manager = _llm_retry_fixture(tmp_path, max_attempts=0)
    response = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "x" * 1024},
                "finish_reason": "stop",
            }
        ]
    }
    manager.node_executor.runners["LLM"].stream_worker = lambda *_args, **_kwargs: {
        "ok": True,
        "response": {"response": {"status_code": 200, "body": response}},
    }

    started = manager.start(workflow_id)
    wait_for_terminal(manager.store, workflow_id, started["id"])
    execution = next(
        item
        for item in manager.store.get_nodes(workflow_id, started["id"])
        if item["type"] == "LLM"
    )

    attempt = execution["attempts"][0]
    assert attempt["request"] is not None
    assert attempt["response"] is None
    assert attempt["response_received"] is True
    assert attempt["truncated_fields"] == ["response"]
    assert execution["response"] == response
    assert execution["status"] == "SUCCESS"


def test_http_retry_after_overrides_configured_retry_interval(tmp_path):
    database = tmp_path / "http-retry-after.sqlite3"
    start = make_node("START")
    http_node = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "HTTP",
            "name": "Retry-After",
            "description": "",
            "request": {"method": "GET", "url": "https://example.invalid"},
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": 1,
                "retry_interval_seconds": 0.25,
                "delay_seconds": 0,
                "retry_non_idempotent": False,
                "retry_statuses": [503],
            },
            "response": {"mode": "AUTO", "success_statuses": [200]},
            "outputs": [],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database,
        [start, http_node, end],
        [(start, http_node), (http_node, end)],
    )
    manager, store = make_manager(tmp_path, repository)
    statuses = iter([503, 200])

    def fake_worker(*_args, **_kwargs):
        status = next(statuses)
        return {
            "ok": True,
            "response": {
                "request": {"method": "GET", "url": "https://example.invalid"},
                "redirects": [],
                "response": {
                    "status_code": status,
                    "headers": (
                        [{"key": "Retry-After", "value": "7"}]
                        if status == 503
                        else []
                    ),
                    "body": {},
                },
            },
        }

    waits = []
    runner = manager.node_executor.runners["HTTP"]
    runner.stream_worker = fake_worker
    runner._wait_interruptibly = lambda _controller, delay: waits.append(delay) or False

    started = manager.start(workflow_id)
    finished = wait_for_terminal(store, workflow_id, started["id"])

    assert finished["status"] == "SUCCESS"
    assert waits[-1] == 7000
    assert HttpNodeRunner._retry_after_milliseconds(
        {
            "headers": [
                {"key": "Retry-After", "value": "7"},
                {"key": "retry-after", "value": "8"},
            ]
        }
    ) is None


@pytest.mark.parametrize(
    ("source", "output_type", "expected_error"),
    [
        (
            "response.choices[-2].message.content",
            "string",
            "LLM_OUTPUT_SOURCE_EVALUATION_ERROR",
        ),
        (
            "response.choices[-1].message",
            "integer",
            "LLM_OUTPUT_TYPE_MISMATCH",
        ),
    ],
)
def test_llm_node_classifies_output_source_and_type_errors(
    tmp_path,
    local_execution_server,
    source,
    output_type,
    expected_error,
):
    base_url, requests = local_execution_server
    database = tmp_path / f"{expected_error}.sqlite3"
    model_repository = ModelProviderRepository(database)
    provider = model_repository.create(
        ModelProviderRecord(
            name="OpenAI compatible",
            api_key="test-key",
            base_url=base_url + "/v1",
            protocol="OPENAI_COMPATIBLE",
            proxy_mode="DIRECT",
            verify_ssl=True,
            models=["local-openai"],
        )
    )
    start = make_node("START")
    llm = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": str(uuid4()),
            "type": "LLM",
            "name": "输出错误分类",
            "description": "",
            "model": {"provider_id": provider.id, "model_name": "local-openai"},
            "context": {"messages": [{"role": "SYSTEM", "content": ""}, {"role": "USER", "content": "测试输出提取"}]},
            "generation": {"parameters": {}},
            "execution": {
                "timeout_seconds": 5,
                "max_attempts": 0,
                "retry_interval_seconds": 0,
                "delay_seconds": 0,
            },
            "outputs": [{"name": "answer", "type": output_type, "source": source}],
        }
    )
    end = make_node("END")
    workflow_id, repository = create_workflow(
        database, [start, llm, end], [(start, llm), (llm, end)]
    )
    manager = WorkflowExecutionManager(
        repository, model_repository, WorkflowExecutionStore(tmp_path / "runs")
    )

    started = manager.start(workflow_id)
    finished = wait_for_terminal(manager.store, workflow_id, started["id"])
    llm_execution = next(
        item
        for item in manager.store.get_nodes(workflow_id, started["id"])
        if item["type"] == "LLM"
    )

    assert finished["status"] == "FAILED"
    assert llm_execution["status"] == "FAILED"
    assert llm_execution["error"]["code"] == expected_error
    assert llm_execution["outputs"] == {}
    assert llm_execution["response"]["choices"][0]["message"]["content"] == "OpenAI OK"
    assert llm_execution["attempt_count"] == 1
    assert llm_execution["attempts"][-1]["status"] == "SUCCESS"
    assert llm_execution["attempts"][-1]["error"] is None
    assert len(requests) == 1
