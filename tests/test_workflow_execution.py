import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

import execution.workflow_execution as workflow_execution_module

from execution.model_providers import ModelProviderRecord, ModelProviderRepository
from execution.node_structural_models import NODE_STRUCTURAL_ADAPTER
from execution.workflow_execution import (
    WorkflowExecutionManager,
    WorkflowExecutionStore,
)
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


def test_worker_registered_after_global_cancel_is_pre_cancelled(monkeypatch):
    interrupted_workers = []
    monkeypatch.setattr(
        workflow_execution_module,
        "interrupt_tool_run",
        lambda worker_id: interrupted_workers.append(worker_id),
    )
    controller = workflow_execution_module._ExecutionController()
    controller.user_cancel.set()

    controller.add_worker("late-worker")

    assert interrupted_workers == ["late-worker"]


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
            requests.append({"method": "POST", "path": self.path, "body": payload})
            if self.path.endswith("/messages"):
                response = {
                    "id": "msg-1",
                    "content": [{"type": "text", "text": "Anthropic OK"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 4, "output_tokens": 2},
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
    assert finished["context"]["final"] == {"question": "hello", "answer": "HELLO"}
    by_type = {item["type"]: item for item in node_documents}
    assert set(by_type) == {"START", "SCRIPT", "END"}
    assert {item["status"] for item in node_documents} == {"SUCCESS"}
    assert by_type["SCRIPT"]["inputs"] == {"question": "hello"}
    assert by_type["SCRIPT"]["outputs"] == {"answer": "HELLO"}
    assert by_type["SCRIPT"]["logs"]["attempts"][-1]["console"][0]["content"] == "HELLO\n"
    assert by_type["END"]["inputs"] == by_type["END"]["outputs"] == {}
    assert next(item for item in finished["nodes"] if item["node_id"] == end.id)["state"] == "FINISHED"


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
    assert script_entry["state"] == "PENDING"

    finished = wait_for_terminal(store, workflow_id, started["id"])
    final_script = next(
        item
        for item in store.get_nodes(workflow_id, started["id"])
        if item["type"] == "SCRIPT"
    )
    assert finished["status"] == "SUCCESS"
    assert final_script["duration_ms"] >= 200


def test_initial_delay_and_retry_interval_are_applied_once_and_timeout_is_converted(
    tmp_path, monkeypatch
):
    waits = []
    worker_timeouts = []
    results = [
        {"ok": False, "error": "temporary failure", "traceback": None},
        {"ok": True, "python_variables": {"result": "ok"}},
    ]

    def record_wait(_controller, delay_milliseconds):
        waits.append(delay_milliseconds)
        return False

    def fake_worker(_payload, _on_log, _run_id, *, timeout_seconds, **_kwargs):
        worker_timeouts.append(timeout_seconds)
        return results.pop(0)

    monkeypatch.setattr(
        workflow_execution_module.WorkflowExecutionManager,
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
            "response.choices[-1].message.content",
            "OpenAI OK",
            "/chat/completions",
        ),
        (
            "ANTHROPIC",
            "local-anthropic",
            "response.content[0].text",
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
            "generation": {"parameters": {"max_tokens": 64}},
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
    assert llm_execution["request"]["max_tokens"] == 64
    assert requests[0]["path"].endswith(path_suffix)
    assert requests[0]["body"]["model"] == model_name
    if protocol == "ANTHROPIC":
        assert requests[0]["body"]["system"] == "系统"
        assert requests[0]["body"]["messages"] == [
            {"role": "user", "content": "示例问题"},
            {"role": "assistant", "content": "示例回答"},
            {"role": "user", "content": "问题：真实请求"},
        ]
    else:
        assert requests[0]["body"]["messages"] == [
            {"role": "system", "content": "系统"},
            {"role": "user", "content": "示例问题"},
            {"role": "assistant", "content": "示例回答"},
            {"role": "user", "content": "问题：真实请求"},
        ]


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
