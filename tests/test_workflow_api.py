from uuid import uuid4

import json
import pytest
import time
from fastapi.testclient import TestClient

from execution.model_providers import ModelProviderRecord, ModelProviderRepository
from web.app import create_app
from web import routes_workflows


START_ID = "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44"
SCRIPT_ID = "550e8400-e29b-41d4-a716-446655440000"
END_ID = "8d9e6679-7425-40de-944b-e07fc1f90ae7"
EDGE_ONE_ID = "9d9e6679-7425-40de-944b-e07fc1f90ae7"
EDGE_TWO_ID = "ad9e6679-7425-40de-944b-e07fc1f90ae7"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_workflows, "DATABASE_PATH", tmp_path / "workflow-api.sqlite3")
    monkeypatch.setattr(routes_workflows, "EXECUTION_ROOT", tmp_path / "executions")
    return TestClient(create_app())


def workflow_body(name=" 质量检测 "):
    execution = {
        "timeout_seconds": 30,
        "max_attempts": 0,
        "retry_interval_seconds": 0,
        "delay_seconds": 0,
    }
    return {
        "name": name,
        "description": "本机开发验证",
        "nodes": [
            {
                "node": {
                    "id": START_ID,
                    "type": "START",
                    "name": "开始",
                    "description": "",
                    "inputs": [{"name": "question", "type": "string", "value": "请审核"}],
                },
                "position_x": 10,
                "position_y": 20,
            },
            {
                "node": {
                    "id": SCRIPT_ID,
                    "type": "SCRIPT",
                    "name": "规则校验",
                    "description": "",
                    "script": "result = context['question']",
                    "execution": execution,
                    "outputs": [{"name": "result", "type": "string", "source": "result"}],
                },
                "position_x": 260,
                "position_y": 20,
            },
            {
                "node": {"id": END_ID, "type": "END", "name": "结束", "description": ""},
                "position_x": 510,
                "position_y": 20,
            },
        ],
        "edges": [
            {"id": EDGE_ONE_ID, "source_node_id": START_ID, "target_node_id": SCRIPT_ID},
            {"id": EDGE_TWO_ID, "source_node_id": SCRIPT_ID, "target_node_id": END_ID},
        ],
    }


def test_workflow_api_crud_round_trip_and_list_shape(client):
    created_response = client.post("/api/workflows", json=workflow_body())
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()["workflow"]
    workflow_id = created["workflow"]["id"]
    assert created["workflow"]["name"] == " 质量检测 "
    assert [node["type"] for node in created["node_models"]] == ["START", "SCRIPT", "END"]

    listing = client.get("/api/workflows")
    assert listing.status_code == 200
    assert listing.json()["workflows"] == [
        {
            "id": workflow_id,
            "name": " 质量检测 ",
            "description": "本机开发验证",
            "updated_at": created["updated_at"],
        }
    ]

    detail = client.get(f"/api/workflows/{workflow_id}")
    assert detail.status_code == 200
    assert detail.json()["workflow"]["workflow"]["edges"] == workflow_body()["edges"]

    updated_body = workflow_body(name="质量检测 v2")
    updated_body["description"] = "新版"
    updated_body["nodes"][1]["node"]["name"] = "新版规则"
    updated = client.put(f"/api/workflows/{workflow_id}", json=updated_body)
    assert updated.status_code == 200, updated.text
    assert updated.json()["workflow"]["node_models"][1]["name"] == "新版规则"

    metadata = client.put(
        f"/api/workflows/{workflow_id}/metadata",
        json={"name": "仅修改名称", "description": "仅修改说明"},
    )
    assert metadata.status_code == 200
    assert metadata.json()["workflow"]["workflow"]["name"] == "仅修改名称"

    deleted = client.delete(f"/api/workflows/{workflow_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/workflows/{workflow_id}").status_code == 404
    assert client.get("/api/workflows").json() == {"workflows": []}


def test_workflow_api_trims_http_url_before_saving(client):
    body = workflow_body("HTTP URL 清理")
    body["nodes"][1]["node"] = {
        "id": SCRIPT_ID,
        "type": "HTTP",
        "name": "请求",
        "description": "",
        "request": {"url": " \t https://example.com/path?q=a%20b \r\n"},
    }

    created = client.post("/api/workflows", json=body)

    assert created.status_code == 201, created.text
    saved = created.json()["workflow"]["node_models"][1]
    assert saved["request"]["url"] == "https://example.com/path?q=a%20b"


def test_workflow_api_applies_and_round_trips_platform_execution_defaults(client):
    body = workflow_body("默认执行策略")
    body["nodes"][1]["node"].pop("execution")

    response = client.post("/api/workflows", json=body)

    assert response.status_code == 201, response.text
    execution = response.json()["workflow"]["node_models"][1]["execution"]
    assert execution == {
        "timeout_seconds": 600.0,
        "max_attempts": 0,
        "retry_interval_seconds": 0.0,
        "delay_seconds": 0.0,
    }


def test_workflow_api_merges_partial_execution_with_platform_defaults(client):
    body = workflow_body("部分执行策略")
    body["nodes"][1]["node"]["execution"] = {"max_attempts": 2}

    response = client.post("/api/workflows", json=body)

    assert response.status_code == 201, response.text
    execution = response.json()["workflow"]["node_models"][1]["execution"]
    assert execution == {
        "timeout_seconds": 600.0,
        "max_attempts": 2,
        "retry_interval_seconds": 0.0,
        "delay_seconds": 0.0,
    }


def test_workflow_api_rejects_invalid_graph_without_creating_record(client):
    body = workflow_body()
    body["nodes"].pop()
    body["edges"].pop()

    response = client.post("/api/workflows", json=body)

    assert response.status_code == 400
    assert "END" in response.json()["detail"]
    assert client.get("/api/workflows").json() == {"workflows": []}


def test_workflow_api_rejects_duplicate_name_and_preserves_first(client):
    assert client.post("/api/workflows", json=workflow_body("同名")).status_code == 201
    second = workflow_body("同名")
    for node_entry in second["nodes"]:
        node_entry["node"]["id"] = str(uuid4())
    second["edges"] = [
        {
            "id": str(uuid4()),
            "source_node_id": second["nodes"][0]["node"]["id"],
            "target_node_id": second["nodes"][1]["node"]["id"],
        },
        {
            "id": str(uuid4()),
            "source_node_id": second["nodes"][1]["node"]["id"],
            "target_node_id": second["nodes"][2]["node"]["id"],
        },
    ]

    response = client.post("/api/workflows", json=second)

    assert response.status_code == 409
    assert response.json() == {"detail": "Workflow 名称已存在，请使用其他名称"}
    assert len(client.get("/api/workflows").json()["workflows"]) == 1


def test_workflow_api_saves_unknown_llm_model_reference_for_runtime_validation(client):
    body = workflow_body()
    llm_id = SCRIPT_ID
    body["nodes"][1]["node"] = {
        "id": llm_id,
        "type": "LLM",
        "name": "模型判断",
        "description": "",
        "model": {"provider_id": "missing", "model_name": "missing"},
        "context": {"messages": [{"role": "SYSTEM", "content": ""}, {"role": "USER", "content": "${question}"}]},
        "generation": {"parameters": {}},
        "execution": {
            "timeout_seconds": 30,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 0,
        },
        "outputs": [],
    }

    response = client.post("/api/workflows", json=body)

    assert response.status_code == 201, response.text
    saved = response.json()["workflow"]["node_models"][1]
    assert saved["model"] == {"provider_id": "missing", "model_name": "missing"}


def test_workflow_api_saves_llm_invalid_parameter_draft_but_run_fails_before_attempt(client):
    provider = ModelProviderRepository(routes_workflows.DATABASE_PATH).create(
        ModelProviderRecord(
            name="local",
            api_key="test-key",
            base_url="http://127.0.0.1:1/v1",
            protocol="OPENAI_COMPATIBLE",
            proxy_mode="DIRECT",
            verify_ssl=True,
            models=["chat"],
        )
    )
    body = workflow_body("LLM 参数草稿")
    body["nodes"][1]["node"] = {
        "id": SCRIPT_ID,
        "type": "LLM",
        "name": "参数草稿",
        "description": "",
        "model": {"provider_id": provider.id, "model_name": "chat"},
        "context": {"messages": [{"role": "SYSTEM", "content": ""}, {"role": "USER", "content": "请回答"}]},
        "generation": {"parameters": {}, "parameters_text": '{"temperature":'},
        "execution": {
            "timeout_seconds": 30,
            "max_attempts": 0,
            "retry_interval_seconds": 0,
            "delay_seconds": 0,
        },
        "outputs": [],
    }

    created = client.post("/api/workflows", json=body)

    assert created.status_code == 201, created.text
    workflow_id = created.json()["workflow"]["workflow"]["id"]
    saved = created.json()["workflow"]["node_models"][1]
    assert saved["generation"]["parameters_text"] == '{"temperature":'
    started = client.post(f"/api/workflows/{workflow_id}/runs")
    assert started.status_code == 202, started.text
    execution_id = started.json()["execution"]["id"]
    deadline = time.monotonic() + 8
    nodes = []
    while time.monotonic() < deadline:
        nodes = client.get(
            f"/api/workflows/{workflow_id}/runs/{execution_id}/nodes"
        ).json()["executions"]
        if any(node["type"] == "LLM" for node in nodes):
            break
        time.sleep(0.03)
    failed = next(node for node in nodes if node["type"] == "LLM")
    assert failed["status"] == "FAILED"
    assert failed["attempt_count"] == 0
    assert failed["error"]["code"] == "LLM_CONFIGURATION_INCOMPLETE"
    assert failed["error"]["details"]["missing_fields"] == ["generation.parameters_text"]


@pytest.mark.parametrize("node_type", ["SCRIPT", "LLM", "HTTP"])
def test_workflow_api_saves_and_round_trips_missing_business_configuration(client, node_type):
    body = workflow_body(f"空白 {node_type}")
    body["nodes"][1]["node"] = {
        "id": SCRIPT_ID,
        "type": node_type,
        "name": f"空白 {node_type}",
        "description": "",
    }

    created = client.post("/api/workflows", json=body)

    assert created.status_code == 201, created.text
    workflow_id = created.json()["workflow"]["workflow"]["id"]
    restored = client.get(f"/api/workflows/{workflow_id}")
    assert restored.status_code == 200, restored.text
    node = restored.json()["workflow"]["node_models"][1]
    assert node["type"] == node_type
    assert node["execution"] == {
        "timeout_seconds": 600.0,
        "max_attempts": 0,
        "retry_interval_seconds": 0.0,
        "delay_seconds": 0.0,
        **(
            {
                "retry_non_idempotent": False,
                "retry_statuses": [408, 429, 500, 502, 503, 504],
            }
            if node_type == "HTTP"
            else {}
        ),
    }


def test_workflow_api_still_rejects_nonempty_invalid_http_url(client):
    body = workflow_body("错误 HTTP")
    body["nodes"][1]["node"] = {
        "id": SCRIPT_ID,
        "type": "HTTP",
        "name": "错误 HTTP",
        "description": "",
        "request": {"url": "not-a-url"},
    }

    response = client.post("/api/workflows", json=body)

    assert response.status_code == 422
    assert "HTTP URL" in response.text


def test_workflow_api_rejects_extra_legacy_draft_fields(client):
    body = workflow_body()
    body["global_variables"] = []

    response = client.post("/api/workflows", json=body)

    assert response.status_code == 422


def test_workflow_run_api_persists_and_returns_real_execution_json(client):
    created = client.post("/api/workflows", json=workflow_body()).json()["workflow"]
    workflow_id = created["workflow"]["id"]

    started_response = client.post(f"/api/workflows/{workflow_id}/runs")
    assert started_response.status_code == 202, started_response.text
    execution_id = started_response.json()["execution"]["id"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        execution = client.get(
            f"/api/workflows/{workflow_id}/runs/{execution_id}"
        ).json()["execution"]
        if execution["status"] in {"SUCCESS", "FAILED", "INTERRUPTED"}:
            break
        time.sleep(0.03)

    assert execution["status"] == "SUCCESS"
    assert execution["context"]["final"] == {"question": "请审核", "result": "请审核"}
    listing = client.get(f"/api/workflows/{workflow_id}/runs").json()["executions"]
    assert listing[0]["id"] == execution_id
    nodes = client.get(
        f"/api/workflows/{workflow_id}/runs/{execution_id}/nodes"
    ).json()["executions"]
    assert {node["type"] for node in nodes} == {"START", "SCRIPT", "END"}
    assert all(node["status"] == "SUCCESS" for node in nodes)


def test_workflow_run_cancel_is_global_and_idempotent(client):
    body = workflow_body()
    body["nodes"][1]["node"]["script"] = "import time\ntime.sleep(30)"
    body["nodes"][1]["node"]["execution"]["timeout_seconds"] = 60
    created = client.post("/api/workflows", json=body).json()["workflow"]
    workflow_id = created["workflow"]["id"]
    execution_id = client.post(f"/api/workflows/{workflow_id}/runs").json()["execution"]["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = client.get(
            f"/api/workflows/{workflow_id}/runs/{execution_id}"
        ).json()["execution"]
        if any(item["state"] == "RUNNING" for item in current["nodes"]):
            break
        time.sleep(0.03)

    assert client.post(
        f"/api/workflows/{workflow_id}/runs/{execution_id}/cancel"
    ).status_code == 200
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        current = client.get(
            f"/api/workflows/{workflow_id}/runs/{execution_id}"
        ).json()["execution"]
        if current["status"] == "INTERRUPTED":
            break
        time.sleep(0.03)
    assert current["status"] == "INTERRUPTED"
    assert client.post(
        f"/api/workflows/{workflow_id}/runs/{execution_id}/cancel"
    ).status_code == 200


def test_execution_directory_opens_fixed_workflow_root(client, monkeypatch):
    created = client.post("/api/workflows", json=workflow_body()).json()["workflow"]
    workflow_id = created["workflow"]["id"]
    opened = []
    monkeypatch.setattr(
        routes_workflows,
        "open_directory_in_explorer",
        lambda path: opened.append(path.resolve()) or str(path.resolve()),
    )

    response = client.post(f"/api/workflows/{workflow_id}/execution-directory")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert opened[0].name == workflow_id
    assert opened[0].parent == routes_workflows.EXECUTION_ROOT.resolve()


def _sse_events(response):
    events = []
    for block in response.text.split("\n\n"):
        data_line = next(
            (line[6:] for line in block.splitlines() if line.startswith("data: ")),
            None,
        )
        if data_line:
            events.append(json.loads(data_line))
    return events


def test_node_test_uses_unsaved_draft_and_context_without_persisting_execution(client):
    created = client.post("/api/workflows", json=workflow_body()).json()["workflow"]
    workflow_id = created["workflow"]["id"]
    draft_node = workflow_body()["nodes"][1]["node"]
    draft_node["script"] = "result = context['temporary'].upper()\nprint(result)"

    started = client.post(
        f"/api/workflows/{workflow_id}/node-tests",
        json={"node": draft_node, "context": {"temporary": "draft value"}},
    )

    assert started.status_code == 202, started.text
    test_id = started.json()["test_id"]
    response = client.get(
        f"/api/workflows/{workflow_id}/node-tests/{test_id}/events"
    )
    events = _sse_events(response)
    final = events[-1]["snapshot"]
    assert events[-1]["type"] == "complete"
    assert final["status"] == "SUCCESS"
    assert final["inputs"] == {"temporary": "draft value"}
    assert final["outputs"] == {"result": "DRAFT VALUE"}
    assert final["logs"]["attempts"][-1]["console"][0]["content"] == "DRAFT VALUE\n"
    assert "workflow_execution_id" not in final
    assert "node_execution_id" not in final
    assert "structural_snapshot" not in final
    assert client.get(f"/api/workflows/{workflow_id}/runs").json() == {"executions": []}
    assert not (routes_workflows.EXECUTION_ROOT / workflow_id).exists()
    restored = client.get(f"/api/workflows/{workflow_id}").json()["workflow"]
    assert restored["node_models"][1]["script"] == "result = context['question']"


@pytest.mark.parametrize(
    ("node", "expected_code", "expected_fields"),
    [
        (
            {"id": SCRIPT_ID, "type": "SCRIPT", "name": "空白脚本", "description": ""},
            "SCRIPT_CONFIGURATION_INCOMPLETE",
            ["script"],
        ),
        (
            {"id": SCRIPT_ID, "type": "LLM", "name": "空白模型", "description": ""},
            "LLM_CONFIGURATION_INCOMPLETE",
            ["model.provider_id", "model.model_name", "context.messages[1].content"],
        ),
        (
            {"id": SCRIPT_ID, "type": "HTTP", "name": "空白请求", "description": ""},
            "HTTP_CONFIGURATION_INCOMPLETE",
            ["request.url"],
        ),
    ],
)
def test_node_test_reports_friendly_missing_configuration_without_execution_json(
    client, node, expected_code, expected_fields
):
    created = client.post("/api/workflows", json=workflow_body()).json()["workflow"]
    workflow_id = created["workflow"]["id"]

    started = client.post(
        f"/api/workflows/{workflow_id}/node-tests",
        json={"node": node, "context": {}},
    )

    assert started.status_code == 202, started.text
    events = _sse_events(
        client.get(
            f"/api/workflows/{workflow_id}/node-tests/{started.json()['test_id']}/events"
        )
    )
    final = events[-1]["snapshot"]
    assert events[-1]["type"] == "complete"
    assert final["status"] == "FAILED"
    assert final["attempt_count"] == 0
    assert final["started_at"] is None
    assert final["duration_ms"] is None
    assert final["error"]["code"] == expected_code
    assert final["error"]["details"]["missing_fields"] == expected_fields
    assert final["error"]["details"]["suggestion"]
    assert node["name"] in final["error"]["message"]
    assert client.get(f"/api/workflows/{workflow_id}/runs").json() == {"executions": []}
    assert not (routes_workflows.EXECUTION_ROOT / workflow_id).exists()


def test_start_node_test_uses_empty_context_and_current_draft_inputs(client):
    created = client.post("/api/workflows", json=workflow_body()).json()["workflow"]
    workflow_id = created["workflow"]["id"]
    draft_node = workflow_body()["nodes"][0]["node"]
    draft_node["inputs"] = [
        {"name": "CurrentValue", "type": "integer", "value": 7}
    ]

    started = client.post(
        f"/api/workflows/{workflow_id}/node-tests",
        json={"node": draft_node, "context": {"ignored": True}},
    ).json()
    events = _sse_events(
        client.get(
            f"/api/workflows/{workflow_id}/node-tests/{started['test_id']}/events"
        )
    )
    final = events[-1]["snapshot"]

    assert final["status"] == "SUCCESS"
    assert final["inputs"] == final["outputs"] == {"CurrentValue": 7}
    assert final["logs"]["input_validation"]["inputs"] == {"CurrentValue": 7}


def test_node_test_is_idempotent_while_running_and_can_be_interrupted(client):
    body = workflow_body()
    body["nodes"][1]["node"]["script"] = "import time\ntime.sleep(30)\nresult = 'late'"
    body["nodes"][1]["node"]["execution"]["timeout_seconds"] = 60
    created = client.post("/api/workflows", json=body).json()["workflow"]
    workflow_id = created["workflow"]["id"]
    node = body["nodes"][1]["node"]

    first = client.post(
        f"/api/workflows/{workflow_id}/node-tests",
        json={"node": node, "context": {}},
    ).json()
    second = client.post(
        f"/api/workflows/{workflow_id}/node-tests",
        json={"node": node, "context": {}},
    ).json()
    assert second["test_id"] == first["test_id"]

    cancelled = client.post(
        f"/api/workflows/{workflow_id}/node-tests/{first['test_id']}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["interrupted"] is True
    events = _sse_events(
        client.get(
            f"/api/workflows/{workflow_id}/node-tests/{first['test_id']}/events"
        )
    )
    final = events[-1]["snapshot"]
    assert events[-1]["type"] == "interrupted"
    assert final["status"] == "INTERRUPTED"
    assert final["error"]["code"] == "USER_INTERRUPTED"
    assert client.get(f"/api/workflows/{workflow_id}/runs").json() == {"executions": []}


def test_end_rejects_node_test_and_workflow_delete_stops_active_test(client):
    body = workflow_body()
    body["nodes"][1]["node"]["script"] = "import time\ntime.sleep(30)"
    body["nodes"][1]["node"]["execution"]["timeout_seconds"] = 60
    created = client.post("/api/workflows", json=body).json()["workflow"]
    workflow_id = created["workflow"]["id"]

    rejected = client.post(
        f"/api/workflows/{workflow_id}/node-tests",
        json={"node": body["nodes"][2]["node"], "context": {}},
    )
    assert rejected.status_code == 400
    assert "END" in rejected.json()["detail"]

    client.post(
        f"/api/workflows/{workflow_id}/node-tests",
        json={"node": body["nodes"][1]["node"], "context": {}},
    )
    deleted = client.delete(f"/api/workflows/{workflow_id}")
    assert deleted.status_code == 200, deleted.text
